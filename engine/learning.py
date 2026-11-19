"""Persist and update the engine's feature weights and decision thresholds."""

import json
import math

from db import get_connection
from engine import decisions
from engine.config import (
    AUTO_DISABLED_THRESHOLD, AUTO_ENABLED_THRESHOLD, AUTO_MAX_UNDO_RATE,
    AUTO_MIN_ACCEPT_RATE, AUTO_MIN_PROPOSALS, DEFAULT_WEIGHTS, LEARNING,
    SETTINGS_KEY_FEEDBACK_COUNTS, SETTINGS_KEY_THRESHOLDS, SETTINGS_KEY_WEIGHTS,
    THRESHOLDS,
)

_COUNT_KEYS = ("accepted", "refused", "auto_applied", "auto_undone")


def _read_setting(key):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM engine_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Stored engine setting '{key}' is not valid JSON.") from exc
    finally:
        conn.close()


def _write_settings(settings):
    if not settings:
        return
    conn = get_connection()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO engine_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, json.dumps(value, sort_keys=True)) for key, value in settings.items()],
            )
    finally:
        conn.close()


def _normalise_weights(values):
    keys = tuple(DEFAULT_WEIGHTS)
    floor = LEARNING["weight_floor"]
    raw = {}
    for key in keys:
        value = values.get(key, DEFAULT_WEIGHTS[key])
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Weight '{key}' must be a finite, non-negative number.")
        raw[key] = max(float(value), floor)
    remaining = 1.0 - floor * len(keys)
    excess = {key: max(0.0, raw[key] - floor) for key in keys}
    total_excess = sum(excess.values())
    if total_excess == 0:
        share = remaining / len(keys)
        return {key: floor + share for key in keys}
    return {key: floor + remaining * excess[key] / total_excess for key in keys}


def get_weights():
    """Return normalized persisted weights, or the configured defaults."""
    stored = _read_setting(SETTINGS_KEY_WEIGHTS)
    if stored is not None and not isinstance(stored, dict):
        raise ValueError("Stored engine weights must be a JSON object.")
    return _normalise_weights({**DEFAULT_WEIGHTS, **(stored or {})})


def _threshold_settings():
    settings = {key: THRESHOLDS[key] for key in ("propose", "margin_full")}
    stored = _read_setting(SETTINGS_KEY_THRESHOLDS)
    if stored is not None:
        if not isinstance(stored, dict):
            raise ValueError("Stored engine thresholds must be a JSON object.")
        settings.update({key: stored[key] for key in settings if key in stored})
    propose, margin = settings["propose"], settings["margin_full"]
    if not isinstance(propose, (int, float)) or isinstance(propose, bool) or not math.isfinite(propose) or not LEARNING["threshold_min"] <= propose <= LEARNING["threshold_max"]:
        raise ValueError("Stored proposal threshold is outside its configured learning range.")
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or not math.isfinite(margin) or margin <= 0:
        raise ValueError("Stored decision margin must be a positive finite number.")
    return settings


def _feedback_snapshot():
    stats = decisions.feedback_stats()
    return {key: int(stats.get(key, 0) or 0) for key in _COUNT_KEYS}


def refresh_thresholds():
    """Adjust the proposal cutoff once enough new accept/reject feedback exists."""
    current = _feedback_snapshot()
    previous = _read_setting(SETTINGS_KEY_FEEDBACK_COUNTS) or {key: 0 for key in _COUNT_KEYS}
    if not isinstance(previous, dict):
        raise ValueError("Stored feedback counts must be a JSON object.")
    if any(current[key] < int(previous.get(key, 0) or 0) for key in _COUNT_KEYS):
        _write_settings({SETTINGS_KEY_FEEDBACK_COUNTS: current})
        return _threshold_settings()

    delta_accepted = current["accepted"] - int(previous.get("accepted", 0) or 0)
    delta_refused = current["refused"] - int(previous.get("refused", 0) or 0)
    event_count = delta_accepted + delta_refused
    if event_count < LEARNING["min_feedback_events"]:
        return _threshold_settings()

    settings = _threshold_settings()
    acceptance_rate = delta_accepted / event_count
    if acceptance_rate < LEARNING["low_accept_rate"]:
        settings["propose"] += LEARNING["threshold_step"]
    elif acceptance_rate > LEARNING["high_accept_rate"]:
        settings["propose"] -= LEARNING["threshold_step"]
    settings["propose"] = min(LEARNING["threshold_max"], max(LEARNING["threshold_min"], settings["propose"]))
    _write_settings({SETTINGS_KEY_THRESHOLDS: settings, SETTINGS_KEY_FEEDBACK_COUNTS: current})
    return settings


def get_thresholds():
    """Return learned cutoffs and enable automation only after enough good outcomes."""
    settings = refresh_thresholds()
    stats = _feedback_snapshot()
    proposal_count = stats["accepted"] + stats["refused"]
    acceptance_rate = stats["accepted"] / proposal_count if proposal_count else 0.0
    undo_rate = stats["auto_undone"] / stats["auto_applied"] if stats["auto_applied"] else 0.0
    auto_ready = (
        proposal_count >= AUTO_MIN_PROPOSALS
        and acceptance_rate >= AUTO_MIN_ACCEPT_RATE
        and undo_rate <= AUTO_MAX_UNDO_RATE
    )
    settings["auto"] = (
        max(AUTO_ENABLED_THRESHOLD, settings["propose"] + LEARNING["threshold_step"])
        if auto_ready else AUTO_DISABLED_THRESHOLD
    )
    return settings


def _factor_map(decision):
    factors = decision.get("factors") or {}
    if not isinstance(factors, dict):
        return {}
    return {int(member_id): values for member_id, values in factors.items() if isinstance(values, dict)}


def learn_from_decision(decision_id, preferred_member_id=None, strong=False, reason_code=None):
    """Update feature weights from a selected candidate versus a close alternative.

    Old decisions without saved feature values still contribute to threshold
    feedback but cannot change feature weights.
    """
    decision = decisions.get_decision(decision_id)
    factors = _factor_map(decision)
    ordered_ids = list(factors)
    recommended_id = decision.get("member_id")
    if decision.get("action") == "ask" and ordered_ids:
        recommended_id = ordered_ids[0]

    preferred_id = preferred_member_id
    if decision.get("status") == "undone":
        rejected_id = decision.get("member_id")
        preferred_id = next((mid for mid in ordered_ids if mid != rejected_id), None)
    elif strong or preferred_id is None:
        rejected_id = recommended_id
        preferred_id = next((mid for mid in ordered_ids if mid != rejected_id), None)
    elif preferred_id == recommended_id:
        rejected_id = next((mid for mid in ordered_ids if mid != preferred_id), None)
    else:
        rejected_id = recommended_id

    updated = False
    weights = get_weights()
    if preferred_id in factors and rejected_id in factors and preferred_id != rejected_id:
        preferred, rejected = factors[preferred_id], factors[rejected_id]
        rate = LEARNING["lr_strong"] if strong else LEARNING["lr"]
        adjusted = {}
        for key, weight in weights.items():
            p_value, r_value = preferred.get(key), rejected.get(key)
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (p_value, r_value)):
                return False
            adjusted[key] = weight + rate * (p_value - r_value)
        _write_settings({SETTINGS_KEY_WEIGHTS: _normalise_weights(adjusted)})
        weights = get_weights()
        updated = True

    # A lead's reason is explicit training feedback. It increases the influence
    # of a criterion the lead says mattered, even when there was no close runner-up.
    reason_factor = {
        "skill_match": "fit", "skill_mismatch": "fit",
        "workload_balance": "load", "workload_concern": "load",
        "related_work": "continuity", "continuity": "continuity",
    }.get(reason_code)
    if reason_factor in weights:
        adjusted = dict(weights)
        adjusted[reason_factor] += LEARNING["lr"]
        _write_settings({SETTINGS_KEY_WEIGHTS: _normalise_weights(adjusted)})
        updated = True

    refresh_thresholds()
    return updated
