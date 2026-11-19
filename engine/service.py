"""Coordinate recommendations, approvals, and task-plan execution."""

from db import initialise_database
from db_operations.helpers import _check_int
from engine import context, decisions, executor, learning
from engine.candidates import eligible_candidates
from engine.config import ALLOW_SELF_APPROVAL, STATUS_COMPLETE
from engine.models import can_approve
from engine.policy import decide
from engine.scoring import rank_candidates


def initialize_service():
    """Create or upgrade the database schema and verify engine requirements."""
    initialise_database()
    return decisions.check_schema()


def _load_task_context(task_id, leaving_member_id=None):
    _check_int(task_id, "Task ID")
    _check_int(leaving_member_id, "Leaving member ID", allow_none=True)
    decisions.check_schema()
    ctx = context.load_context()
    task = ctx["tasks"].get(task_id)
    if task is None:
        raise ValueError("Task ID does not exist.")
    if task["status"] == STATUS_COMPLETE:
        raise ValueError("A completed task cannot be reallocated.")
    if leaving_member_id is not None:
        if leaving_member_id not in ctx["members"]:
            raise ValueError("Leaving member ID does not exist.")
        if leaving_member_id not in {a["member_id"] for a in task["assignees"]}:
            raise ValueError("Leaving member is not assigned to this task.")
    return ctx, task


def _mark_stale(decision_id, note):
    decisions.set_status(decision_id, "stale", note=note)


def _execute_auto(decision):
    plan = decision["plan"]
    decision_id = decision["decision_id"]
    try:
        executor.execute(plan, decision_id=decision_id)
    except Exception:
        try:
            _mark_stale(decision_id, "Automatic plan could not be applied.")
        except ValueError:
            pass
        raise
    try:
        decisions.set_status(decision_id, "executed_auto")
    except Exception:
        # Keep the assignment state and the decision state in sync if resolution fails.
        executor.execute(executor.invert(plan), decision_id=decision_id)
        raise
    learning.refresh_thresholds()
    return decisions.get_decision(decision_id)


def recommend_task(task_id, leaving_member_id=None):
    """Create an evidence-backed wait, clarification request, or proposal."""
    ctx, task = _load_task_context(task_id, leaving_member_id)
    decisions.expire_older_than()

    existing = decisions.open_decision_for(task_id, leaving_member_id)
    if existing:
        if existing["action"] == "auto" and existing.get("plan"):
            # Older application versions could leave a pending auto-decision.
            # It must now be presented as a proposal and wait for lead approval.
            if executor.can_apply(existing["plan"], ctx):
                existing = decisions.convert_pending_auto_to_proposal(existing["decision_id"])
                return existing
            _mark_stale(existing["decision_id"], "Task assignments changed before this legacy decision was reviewed.")
        elif existing["action"] in ("propose", "auto") and existing.get("plan"):
            if not executor.can_apply(existing["plan"], ctx):
                _mark_stale(existing["decision_id"], "Task assignments changed since this proposal was created.")
            else:
                return existing
        elif existing["action"] == "wait":
            blocked = not task["assignees"] and any(
                ctx["tasks"].get(dep["predecessor_id"], {}).get("status") != STATUS_COMPLETE
                for dep in task["dependencies"]
            )
            predecessor_wait = "Waiting for predecessor task(s) to complete:" in existing.get("reason", "")
            if blocked or not predecessor_wait:
                return existing
            _mark_stale(existing["decision_id"], "Re-evaluated because this task already has an assignee.")
        else:
            # Questions and other unchanged wait decisions remain open for user action.
            return existing

    leaving = ctx["members"].get(leaving_member_id) if leaving_member_id is not None else None
    # Dependencies gate first allocation. An in-progress or already staffed task can
    # still be reallocated while its predecessor is unfinished.
    blocked_predecessors = [] if task["assignees"] else [
        dep for dep in task["dependencies"]
        if ctx["tasks"].get(dep["predecessor_id"], {}).get("status") != STATUS_COMPLETE
    ]
    if blocked_predecessors:
        names = ", ".join(dep["predecessor_name"] for dep in blocked_predecessors)
        result = {
            "task_id": task_id,
            "leaving_member_id": leaving_member_id,
            "action": "wait",
            "confidence": 1.0,
            "reason": f"Waiting for predecessor task(s) to complete: {names}.",
            "revisit_when": "All predecessor tasks are complete.",
        }
    else:
        eligible, rejected, _gap = eligible_candidates(ctx, task_id, leaving_member_id)
        ranked = rank_candidates(ctx, task_id, eligible, weights=learning.get_weights())
        result = decide(task, leaving, ranked, rejected, thresholds=learning.get_thresholds())

    if result["action"] == "propose":
        result["plan"] = executor.make_plan(task_id, leaving_member_id, result["member_id"])
        if not executor.can_apply(result["plan"], ctx):
            raise RuntimeError("The generated task plan does not match the current assignments.")

    decision_id = decisions.create_decision(result)
    saved = decisions.get_decision(decision_id)
    return saved


def _approver_context(approver_id):
    _check_int(approver_id, "Approver ID")
    ctx = context.load_context()
    approver = ctx["members"].get(approver_id)
    if approver is None:
        raise ValueError("Approver ID does not exist.")
    if not can_approve(approver):
        raise ValueError("This member is not allowed to approve task changes.")
    return ctx


def _check_self_approval(decision, approver_id, member_id=None):
    involved_ids = {decision.get("leaving_member_id"), member_id} - {None}
    if not ALLOW_SELF_APPROVAL and approver_id in involved_ids:
        raise ValueError("A member involved in a reallocation cannot approve it themselves.")


def approve_decision(decision_id, approver_id, member_id=None, note=None,
                     reason_code=None, rationale=None):
    """Apply a proposed allocation only after explicit lead approval."""
    _check_int(decision_id, "Decision ID")
    decision = decisions.get_decision(decision_id)
    if decision["action"] != "propose":
        raise ValueError("A clarification request must be answered before a proposal can be approved.")
    if decision["status"] != "pending":
        raise ValueError("Only pending decisions can be approved.")

    ctx = _approver_context(approver_id)
    chosen_id = decision.get("member_id")
    if member_id is not None and member_id != chosen_id:
        raise ValueError("A proposal can only be approved for its recommended member.")
    member_id = chosen_id
    plan = decision.get("plan")
    if not plan:
        raise ValueError("The proposal has no executable plan.")

    _check_self_approval(decision, approver_id, member_id)
    ctx, _task = _load_task_context(decision["task_id"], decision.get("leaving_member_id"))
    eligible, _rejected, _gap = eligible_candidates(ctx, decision["task_id"], decision.get("leaving_member_id"))
    if member_id not in {candidate["member_id"] for candidate in eligible} or not executor.can_apply(plan, ctx):
        _mark_stale(decision_id, "The recommended member or plan is no longer valid for the current task state.")
        raise ValueError("Decision is stale; request a new recommendation.")

    executor.execute(plan, decision_id=decision_id)
    try:
        decisions.set_status(decision_id, "approved", approver_id=approver_id, note=note)
    except Exception:
        executor.execute(executor.invert(plan), decision_id=decision_id)
        raise
    decisions.update_detail(decision_id, {
        "outcome": "approved and applied", "lead_response": note,
        "feedback_reason": {"code": reason_code, "label": rationale} if reason_code else None
    })
    learning.learn_from_decision(decision_id, preferred_member_id=member_id, reason_code=reason_code)
    return decisions.get_decision(decision_id)


def reject_decision(decision_id, approver_id, note=None, reason_code=None, rationale=None):
    """Reject a pending proposal, ask, or wait decision."""
    _check_int(decision_id, "Decision ID")
    decision = decisions.get_decision(decision_id)
    if decision["status"] != "pending":
        raise ValueError("Only pending decisions can be rejected.")
    if decision["action"] not in ("propose", "ask", "wait"):
        raise ValueError("This decision cannot be rejected.")
    _approver_context(approver_id)
    decisions.set_status(decision_id, "rejected", approver_id=approver_id, note=note)
    decisions.update_detail(decision_id, {
        "outcome": "rejected", "lead_response": note,
        "feedback_reason": {"code": reason_code, "label": rationale} if reason_code else None
    })
    learning.learn_from_decision(decision_id, reason_code=reason_code)
    learning.refresh_thresholds()
    return decisions.get_decision(decision_id)


def respond_to_clarification(decision_id, approver_id, preferred_member_id=None,
                             response_text=None, prefer_workload=False):
    """Record a lead's clarification and reassess; this never changes assignments."""
    _check_int(decision_id, "Decision ID")
    decision = decisions.get_decision(decision_id)
    if decision["status"] != "pending" or decision["action"] != "ask":
        raise ValueError("Only a pending clarification request can be answered.")
    _approver_context(approver_id)
    ctx, task = _load_task_context(decision["task_id"], decision.get("leaving_member_id"))
    eligible, rejected, _gap = eligible_candidates(ctx, decision["task_id"], decision.get("leaving_member_id"))
    if preferred_member_id is not None:
        _check_int(preferred_member_id, "Preferred member ID")
        if preferred_member_id not in {m["member_id"] for m in eligible}:
            raise ValueError("The preferred member is no longer eligible for this task.")
    if prefer_workload:
        if not eligible:
            preferred_member_id = None
        else:
            preferred_member_id = min(eligible, key=lambda m: (m["workload"], m["member_id"]))["member_id"]

    response = {
        "approver_id": approver_id,
        "text": (response_text or "").strip(),
        "preferred_member_id": preferred_member_id,
        "preference": "workload balance" if prefer_workload else ("specific candidate" if preferred_member_id else "additional context"),
    }
    decisions.update_detail(decision_id, {
        "clarification_response": response,
        "lead_response": response["text"],
        "outcome": "clarification recorded; reassessment created"
    })
    decisions.set_status(decision_id, "stale", approver_id=approver_id,
                         note=response["text"] or response["preference"])

    # The preference is recorded as a learning example and used directly for this
    # reassessment. It remains a proposal: only a subsequent approval applies it.
    if preferred_member_id is not None:
        learning.learn_from_decision(decision_id, preferred_member_id=preferred_member_id)
    ranked = rank_candidates(ctx, task["task_id"], eligible, weights=learning.get_weights())
    if preferred_member_id is None:
        reassessed = recommend_task(task["task_id"], decision.get("leaving_member_id"))
    else:
        selected = next((c for c in ranked if c.member_id == preferred_member_id), None)
        if selected is None:
            reassessed = recommend_task(task["task_id"], decision.get("leaving_member_id"))
        else:
            comparison = [{
                "member_id": c.member_id, "name": c.name, "score": round(c.score, 3),
                "breakdown": c.breakdown(), "factor_values": c.factor_values(),
                "evidence": [{"factor": f.name, "value": round(f.value, 3),
                              "weight": round(f.weight, 3), "contribution": round(f.contribution, 3),
                              "note": f.note} for f in c.factors]
            } for c in ranked[:5]]
            reason = (f"{selected.name} is recommended after the lead clarified a preference for "
                      f"{response['preference']}.\n{response['text']}" if response["text"] else
                      f"{selected.name} is recommended after the lead clarified a preference for {response['preference']}.")
            if len(ranked) > 1:
                reason += (f"\nComparative score: {selected.score:.3f}. "
                           "Other eligible candidates remain listed for review.")
            result = {
                "task_id": task["task_id"], "leaving_member_id": decision.get("leaving_member_id"),
                "action": "propose", "confidence": max(0.0, min(1.0, selected.score)),
                "reason": reason, "member_id": selected.member_id,
                "factors": {str(c.member_id): c.factor_values() for c in ranked[:5]},
                "alternatives": [c for c in comparison if c["member_id"] != selected.member_id][:3],
                "candidate_comparison": comparison, "breakdown": selected.breakdown(),
                "evidence": next(c["evidence"] for c in comparison if c["member_id"] == selected.member_id),
                "approval_required": True,
                "clarification_response": response,
            }
            result["plan"] = executor.make_plan(task["task_id"], decision.get("leaving_member_id"), selected.member_id)
            if not executor.can_apply(result["plan"], ctx):
                raise ValueError("The task changed during reassessment; request a fresh recommendation.")
            reassessed = decisions.get_decision(decisions.create_decision(result))

    decisions.update_detail(decision_id, {"reassessment_decision_id": reassessed["decision_id"]})
    return {"clarification": decisions.get_decision(decision_id), "reassessment": reassessed}


def undo_decision(decision_id, approver_id, note=None):
    """Reverse an approved or automatic plan when its inverse still applies."""
    _check_int(decision_id, "Decision ID")
    decision = decisions.get_decision(decision_id)
    if decision["status"] not in ("approved", "executed_auto"):
        raise ValueError("Only an approved or automatic decision can be undone.")
    ctx = _approver_context(approver_id)
    plan = decision.get("plan")
    if not plan:
        raise ValueError("The decision has no plan to undo.")
    inverse = executor.invert(plan)
    if not executor.can_apply(inverse, ctx):
        raise ValueError("The inverse plan no longer applies to the current task state.")
    executor.execute(inverse, decision_id=decision_id)
    try:
        decisions.set_status(decision_id, "undone", approver_id=approver_id, note=note)
    except Exception:
        executor.execute(plan, decision_id=decision_id)
        raise
    learning.learn_from_decision(decision_id, strong=(decision["action"] == "auto"))
    return decisions.get_decision(decision_id)


def reconsider_decision(decision_id):
    """Close a pending decision as stale and calculate a fresh recommendation."""
    _check_int(decision_id, "Decision ID")
    decision = decisions.get_decision(decision_id)
    if decision["status"] != "pending" or decision["action"] not in ("propose", "ask", "wait"):
        raise ValueError("Only a pending proposal, ask, or wait decision can be reconsidered.")
    _mark_stale(decision_id, "Reconsidered against the current team and task state.")
    return recommend_task(decision["task_id"], decision.get("leaving_member_id"))
