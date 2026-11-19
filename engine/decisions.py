import json
import sqlite3

from db import get_connection
from engine.config import ACTIONS, PROPOSAL_EXPIRY_HOURS, STATUSES

ALLOWED = {
    "pending": {"approved","rejected","expired","stale","executed_auto"},
    "approved": {"undone"},
    "executed_auto": {"undone"},
}
_DETAIL_KEYS = {
    "questions","question","options","breakdown","revisit_when","alternatives",
    "candidate_comparison", "approval_required", "clarification_response",
    "clarification_at", "reassessment_decision_id", "outcome", "evidence",
    "lead_response", "legacy_auto_converted", "feedback_reason"
}
_DECISION_COLUMNS = {
    "decision_id","task_id","leaving_member_id",
    "member_id","action","status",
    "plan","confidence","reason",
    "factors","detail","approver_id",
    "note","created_at","resolved_at"
}

for _status, _targets in ALLOWED.items():
    if not({_status}|_targets) <= set(STATUSES):
        raise ValueError(f"ALLOWED in decisions.py uses a status not in config.STATUSES: {_status}")


def check_schema():
    """Raise RuntimeError, saying exactly what to fix, if the database cannot support the engine."""
    conn = get_connection()
    try:
        table = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone()
        if table is None:
            raise RuntimeError("The decisions table is missing: create it in db.initialise_database().")
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
        if _DECISION_COLUMNS - columns:
            raise RuntimeError(f"The decisions table lacks columns: {sorted(_DECISION_COLUMNS - columns)}.")
        for value in (*ACTIONS, *STATUSES):
            if f"'{value}'" not in table["sql"]:
                raise RuntimeError(f"The decisions table does not allow '{value}'. Its CHECK clauses must "
                                   f"match config.ACTIONS and config.STATUSES exactly.")
        index = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_one_open_decision'").fetchone()
        index_sql = (index["sql"] or "").upper() if index else ""
        if "UNIQUE" not in index_sql or "COALESCE" not in index_sql:
            raise RuntimeError("idx_one_open_decision must be a UNIQUE index on "
                               "(task_id, COALESCE(leaving_member_id, 0)) WHERE status = 'pending'.")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engine_settings'").fetchone() is None:
            raise RuntimeError("The engine_settings table is missing: create it in db.initialise_database().")
        history = {r["name"] for r in conn.execute("PRAGMA table_info(history)")}
        if "decision_id" not in history:
            raise RuntimeError("The history table needs a decision_id column to link changes to decisions.")
        return True
    finally:
        conn.close()


def _dump(value):
    return None if value is None else json.dumps(value)

def _load(text):
    return json.loads(text) if text else None

def _to_dict(row):
    data = dict(row)
    data["plan"] = _load(data["plan"])
    factors = _load(data["factors"]) or {}
    data["factors"] = {int(k): v for k, v in factors.items()}
    data.update(_load(data.pop("detail")) or {})
    for key in _DETAIL_KEYS:
        data.setdefault(key, None)
    return data

def _validate(d):
    for key in ("task_id", "action", "confidence", "reason"):
        if key not in d:
            raise ValueError(f"Decision is missing '{key}'.")
    if d["action"] not in ACTIONS:
        raise ValueError(f"Unknown action '{d['action']}'.")
    if not isinstance(d["reason"], str) or not d["reason"].strip():
        raise ValueError("Every decision needs a reason.")
    if not isinstance(d["confidence"], (int, float)) or not -1e-9 <= d["confidence"] <= 1 + 1e-9:
        raise ValueError("Confidence must be a number between 0 and 1.")
    if d["action"] in ("propose", "auto") and not (d.get("member_id") and d.get("plan")):
        raise ValueError(f"A '{d['action']}' decision needs a member_id and a plan.")
    if d["action"] == "ask" and not d.get("options"):
        raise ValueError("A question needs options to choose from.")

def _select(clauses=(), params=(), newest_first=True, limit=100):
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    order = "DESC" if newest_first else "ASC"
    conn = get_connection()
    try:
        rows = conn.execute(f"SELECT * FROM decisions {where} ORDER BY decision_id {order} LIMIT ?",
                            (*params, limit)).fetchall()
        return [_to_dict(r) for r in rows]
    finally:
        conn.close()

def create_decision(d):
    _validate(d)
    detail = {k: d[k] for k in _DETAIL_KEYS if d.get(k) is not None}
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO decisions (task_id, leaving_member_id, member_id, action, confidence, "
                "reason, plan, factors, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                (d["task_id"], d.get("leaving_member_id"), d.get("member_id"), d["action"],
                 d["confidence"], d["reason"], _dump(d.get("plan")), _dump(d.get("factors")),
                 json.dumps(detail)))
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        open_one = conn.execute(
            "SELECT 1 FROM decisions WHERE status = 'pending' AND task_id = ? "
            "AND COALESCE(leaving_member_id, 0) = COALESCE(?, 0)",
            (d["task_id"], d.get("leaving_member_id"))).fetchone()
        if open_one:
            raise ValueError("An open decision already exists for this task.") from e
        raise ValueError("The task or a member referenced by this decision does not exist.") from e
    finally:
        conn.close()

def get_decision(decision_id):
    found = _select(["decision_id = ?"], (decision_id,), limit=1)
    if not found:
        raise ValueError("Decision does not exist.")
    return found[0]

def open_decision_for(task_id, leaving_member_id=None):
    found = _select(["status = 'pending'", "task_id = ?", "COALESCE(leaving_member_id, 0) = COALESCE(?, 0)"],
                    (task_id, leaving_member_id), limit=1)
    return found[0] if found else None

def list_decisions(status=None, action=None, limit=100):
    clauses, params = [], []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if action is not None:
        clauses.append("action = ?")
        params.append(action)
    return _select(clauses, params, limit=limit)

def list_pending(action=None):
    clauses, params = ["status = 'pending'"], []
    if action is not None:
        clauses.append("action = ?")
        params.append(action)
    return _select(clauses, params, newest_first=False, limit=1000)

def set_status(decision_id, new_status, approver_id=None, note=None):
    if new_status not in STATUSES:
        raise ValueError(f"Unknown status '{new_status}'.")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
            if row is None:
                raise ValueError("Decision does not exist.")
            if new_status not in ALLOWED.get(row["status"], set()):
                raise ValueError(f"Cannot go from '{row['status']}' to '{new_status}'.")
            conn.execute(
                "UPDATE decisions SET status = ?, approver_id = COALESCE(?, approver_id), "
                "note = COALESCE(?, note), resolved_at = CURRENT_TIMESTAMP WHERE decision_id = ?",
                (new_status, approver_id, note, decision_id))
            return True
    finally:
        conn.close()


def attach_plan(decision_id, member_id, plan):
    if not plan:
        raise ValueError("A plan is required.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE decisions SET member_id = ?, plan = ? WHERE decision_id = ? AND status = 'pending'",
                (member_id, json.dumps(plan), decision_id))
            if cursor.rowcount == 0:
                raise ValueError("Decision does not exist or is no longer pending.")
            return True
    finally:
        conn.close()


def update_detail(decision_id, updates):
    """Merge auditable explanation/clarification fields into a decision."""
    if not isinstance(updates, dict):
        raise ValueError("Decision detail updates must be a mapping.")
    conn = get_connection()
    try:
        with conn:
            row = conn.execute("SELECT detail FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
            if row is None:
                raise ValueError("Decision does not exist.")
            detail = _load(row["detail"]) or {}
            detail.update(updates)
            conn.execute("UPDATE decisions SET detail = ? WHERE decision_id = ?",
                         (json.dumps(detail), decision_id))
        return get_decision(decision_id)
    finally:
        conn.close()


def convert_pending_auto_to_proposal(decision_id):
    """Safely migrate a legacy pending auto-decision into a reviewable proposal."""
    conn = get_connection()
    try:
        with conn:
            row = conn.execute("SELECT action, status, reason, detail FROM decisions WHERE decision_id = ?",
                               (decision_id,)).fetchone()
            if row is None:
                raise ValueError("Decision does not exist.")
            if row["status"] != "pending" or row["action"] != "auto":
                raise ValueError("Only pending automatic decisions can be converted.")
            detail = _load(row["detail"]) or {}
            detail.update({"approval_required": True, "legacy_auto_converted": True})
            reason = row["reason"] + "; converted to a proposal because allocation requires lead approval."
            conn.execute("UPDATE decisions SET action = 'propose', reason = ?, detail = ? WHERE decision_id = ?",
                         (reason, json.dumps(detail), decision_id))
        return get_decision(decision_id)
    finally:
        conn.close()


def expire_older_than(hours=PROPOSAL_EXPIRY_HOURS, actions=("propose", "ask")):
    if not isinstance(hours, int) or hours < 0:
        raise ValueError("hours must be a whole number, zero or more.")
    marks = ",".join("?" for _ in actions)
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                f"UPDATE decisions SET status = 'expired', resolved_at = CURRENT_TIMESTAMP "
                f"WHERE status = 'pending' AND action IN ({marks}) AND created_at <= datetime('now', ?)",
                (*actions, f"-{hours} hours"))
            return cursor.rowcount
    finally:
        conn.close()


# ---------- outcomes, for learning -----------------------------------------------------------
def feedback_stats():
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN action = 'propose' AND status = 'approved' THEN 1 ELSE 0 END), 0) AS accepted,
              COALESCE(SUM(CASE WHEN action = 'propose' AND status IN ('rejected','undone') THEN 1 ELSE 0 END), 0) AS refused,
              COALESCE(SUM(CASE WHEN action = 'auto' AND status IN ('executed_auto','undone') THEN 1 ELSE 0 END), 0) AS auto_applied,
              COALESCE(SUM(CASE WHEN action = 'auto' AND status = 'undone' THEN 1 ELSE 0 END), 0) AS auto_undone
            FROM decisions""").fetchone()
        return dict(row)
    finally:
        conn.close()
