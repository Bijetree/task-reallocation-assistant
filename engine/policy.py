from engine.config import (
    LOW_IMPACT_MAX_DURATION, LOW_IMPACT_STATUS, THRESHOLDS, URGENT_BLOCKS_AUTO_AT, urgency_from_priority
)
from engine.scoring import explain, explain_margin

def impact_blockers(task):
    blockers = []
    if task["status"] != LOW_IMPACT_STATUS:
        blockers.append(f"It is already '{task['status']}'")
    if task["duration"] > LOW_IMPACT_MAX_DURATION:
        blockers.append(f"It is long ({task['duration']},limit{LOW_IMPACT_MAX_DURATION})")
    if urgency_from_priority(task["priority"]) > URGENT_BLOCKS_AUTO_AT:
        blockers.append("It is urgent.")
    return blockers

def is_low_impact(task):
    return not impact_blockers(task)

def confidence_of(ranked, margin_full):
    if not ranked:
        return 0.0
    best = ranked[0].score
    runner_up = ranked[1].score if len(ranked)>1 else 0.0
    return best*min(1.0, (best-runner_up)/margin_full)

def _summary(candidate):
    return {
        "member_id": candidate.member_id,
        "name": candidate.name,
        "score": round(candidate.score, 3),
        "breakdown": candidate.breakdown(),
        "factor_values": candidate.factor_values(),
        "evidence": [{"factor": f.name, "value": round(f.value, 3),
                      "weight": round(f.weight, 3), "contribution": round(f.contribution, 3),
                      "note": f.note} for f in candidate.factors]
    }

def decide(task, leaving, ranked, rejected, thresholds=None):
    t = {**THRESHOLDS, **(thresholds or {})}
    base = {
        "task_id": task["task_id"],
        "leaving_member_id": leaving["member_id"] if leaving else None
    }
    if not ranked:
        why = "\n".join(f"- {reason}" for reason in rejected.values()) or "- No other team members are available."
        return {
            **base, 
            "action": "wait",
            "confidence": 1.0,
            "reason": f"No eligible person is available for ‘{task['name']}’.\nReasons:\n{why}",
            "revisit_when": "A member becomes available or gains missing skills."
        }
    best = ranked[0]
    confidence = confidence_of(ranked, t["margin_full"])
    if confidence < t["propose"]:
        if len(ranked)>1 and best.score - ranked[1].score < t["margin_full"]:
            reason = (f"The top candidates have similar scores: {best.name} ({best.score:.2f}) and "
                      f"{ranked[1].name} ({ranked[1].score:.2f}).\nMore guidance is needed before recommending an assignee.")
        else:
             reason = f"The best candidate, {best.name}, scores only {best.score:.2f}."
        return {
            **base,
            "action": "ask",
            "confidence": round(confidence,4),
            "reason": reason,
            "question": f"Who should take over '{task['name']}'?",
            "factors": {str(c.member_id): c.factor_values() for c in ranked[:3]},
            "options": [_summary(c) for c in ranked[:3]],
            "candidate_comparison": [_summary(c) for c in ranked[:5]],
            "breakdown": best.breakdown(),
            "approval_required": True
        }
    reason = explain(best)
    if len(ranked)>1:
        margin_text = explain_margin(best, ranked[1])
        if margin_text:
            reason += f"\n- Candidate comparison: {margin_text}."

    # Recommendations are advisory. Allocation is always gated by an explicit
    # lead approval in service.approve_decision, regardless of score.
    action = "propose"

    return {
        **base,
        "action": action,
        "reason": reason,
        "confidence": round(confidence, 4),
        "member_id": best.member_id,
        "factors": {str(c.member_id): c.factor_values() for c in ranked[:3]},
        "alternatives": [_summary(c) for c in ranked[1:3]],
        "breakdown": best.breakdown(),
        "candidate_comparison": [_summary(c) for c in ranked[:5]],
        "evidence": _summary(best)["evidence"],
        "approval_required": True
    }
