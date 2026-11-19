"""Post-commit event handlers and a periodic sweep for task reallocation.

Call handlers after the corresponding database operation commits. Call
run_scheduled_sweep from a periodic job or a simulated next-day action.
"""

from engine import context, decisions, learning, service
from engine.candidates import eligible_candidates
from engine.config import OVERLOAD_RATIO, STATUS_COMPLETE


def _active(task):
    return task is not None and task["status"] != STATUS_COMPLETE


def _task(ctx, task_id):
    task = ctx["tasks"].get(task_id)
    if task is None:
        raise ValueError("Task ID does not exist.")
    return task


def _ready(ctx, task):
    # Dependency completion is required before first allocation, not for an
    # already staffed task that needs replacement capacity.
    return bool(task["assignees"]) or all(
        ctx["tasks"].get(dep["predecessor_id"], {}).get("status") == STATUS_COMPLETE
        for dep in task["dependencies"]
    )


def _recommend_or_reconsider(task_id, leaving_member_id=None):
    ctx = context.load_context()
    task = _task(ctx, task_id)
    existing = decisions.open_decision_for(task_id, leaving_member_id)
    if existing and existing["action"] == "wait":
        if not _ready(ctx, task):
            return existing
        return service.reconsider_decision(existing["decision_id"])
    return service.recommend_task(task_id, leaving_member_id)


def task_became_unassigned(task_id):
    """Recommend an initial allocation when an active task has no assignees."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if _active(task) and not task["assignees"]:
        return _recommend_or_reconsider(task_id)
    return None


def task_created(task_id):
    """Call after a new task is fully configured with skills and dependencies."""
    return task_became_unassigned(task_id)


def task_unassigned(task_id):
    """Call after an unassignment has committed."""
    return task_became_unassigned(task_id)


def member_became_unavailable(member_id):
    """Find replacements for the unavailable member's unfinished tasks."""
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if member["available"]:
        raise ValueError("The member is still marked available.")
    return [
        service.recommend_task(task["task_id"], leaving_member_id=member_id)
        for task in ctx["tasks"].values()
        if _active(task) and member_id in {a["member_id"] for a in task["assignees"]}
    ]


def member_became_available(member_id):
    """Revisit wait decisions when the returning member makes a candidate eligible."""
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if not member["available"]:
        raise ValueError("The member is still marked unavailable.")
    refreshed = []
    for waiting in decisions.list_pending(action="wait"):
        task = ctx["tasks"].get(waiting["task_id"])
        if not _active(task):
            continue
        leaving_id = waiting.get("leaving_member_id")
        if leaving_id == member_id:
            decisions.set_status(waiting["decision_id"], "stale", note="The unavailable member returned.")
            continue
        if leaving_id is not None and leaving_id not in {a["member_id"] for a in task["assignees"]}:
            decisions.set_status(waiting["decision_id"], "stale", note="The task assignment changed while waiting.")
            continue
        eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"], leaving_id)
        if _ready(ctx, task) and member_id in {candidate["member_id"] for candidate in eligible}:
            refreshed.append(service.reconsider_decision(waiting["decision_id"]))
    return refreshed


def member_availability_changed(member_id):
    """Dispatch an availability event based on the member's committed state."""
    member = context.load_context()["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    return member_became_available(member_id) if member["available"] else member_became_unavailable(member_id)


def member_became_overloaded(member_id, ratio=OVERLOAD_RATIO):
    """Suggest moving one large, relatively low-urgency task from an overloaded member."""
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or ratio <= 1:
        raise ValueError("Overload ratio must be a number greater than 1.")
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if not member["available"]:
        return []
    available = [m for m in ctx["members"].values() if m["available"]]
    if not available:
        return []
    average = sum(m["workload"] for m in available) / len(available)
    if average <= 0 or member["workload"] <= average * ratio:
        return []
    tasks = [
        task for task in ctx["tasks"].values()
        if _active(task) and member_id in {a["member_id"] for a in task["assignees"]}
    ]
    if not tasks:
        return []
    task = sorted(tasks, key=lambda t: (-t["duration"], t["priority"], t["task_id"]))[0]
    return [service.recommend_task(task["task_id"], leaving_member_id=member_id)]


def task_status_changed(task_id, old_status, new_status):
    """Recheck unassigned work as tasks complete or return to unfinished status."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if task["status"] != new_status:
        raise ValueError("The supplied new status does not match the stored task status.")
    results = []
    if new_status == STATUS_COMPLETE and old_status != STATUS_COMPLETE:
        results.extend(predecessor_completed(task_id))
    elif old_status == STATUS_COMPLETE and new_status != STATUS_COMPLETE and not task["assignees"]:
        result = task_became_unassigned(task_id)
        if result is not None:
            results.append(result)
    return results


def predecessor_completed(task_id):
    """Recommend allocation for dependent tasks whose predecessors are all complete."""
    ctx = context.load_context()
    _task(ctx, task_id)
    results = []
    for task in ctx["tasks"].values():
        if not _active(task) or task["assignees"]:
            continue
        if not any(dep["predecessor_id"] == task_id for dep in task["dependencies"]):
            continue
        ready = all(
            ctx["tasks"].get(dep["predecessor_id"], {}).get("status") == STATUS_COMPLETE
            for dep in task["dependencies"]
        )
        if ready:
            results.append(_recommend_or_reconsider(task["task_id"]))
    return results


def dependency_changed(task_id):
    """Recheck an unassigned task after its dependency links change."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if not _active(task) or task["assignees"]:
        return None
    ready = all(
        ctx["tasks"].get(dep["predecessor_id"], {}).get("status") == STATUS_COMPLETE
        for dep in task["dependencies"]
    )
    return _recommend_or_reconsider(task_id) if ready else None


def task_duration_increased(task_id, old_duration, new_duration):
    """Recheck workload pressure when task duration grows."""
    if new_duration <= old_duration:
        return []
    ctx = context.load_context()
    task = _task(ctx, task_id)
    results = []
    for member_id in {a["member_id"] for a in task["assignees"]}:
        results.extend(member_became_overloaded(member_id))
    if task["slack"] <= 0:
        result = task_slack_exhausted(task_id)
        if result is not None:
            results.append(result)
    return results


def task_slack_exhausted(task_id):
    """Review staffing when an unfinished task reaches zero or negative slack."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if not _active(task) or task["slack"] > 0:
        return None
    assignees = [a["member_id"] for a in task["assignees"]]
    if not assignees:
        return _recommend_or_reconsider(task_id)
    leaving_id = max(assignees, key=lambda mid: (ctx["members"][mid]["workload"], mid))
    return _recommend_or_reconsider(task_id, leaving_member_id=leaving_id)


def member_skill_removed(member_id, skill_id):
    """Recheck active tasks whose assigned group lost required-skill coverage."""
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if skill_id in {s["skill_id"] for s in member["skills"]}:
        raise ValueError("The member still has this skill.")
    affected = []
    for task in ctx["tasks"].values():
        if not _active(task) or member_id not in {a["member_id"] for a in task["assignees"]}:
            continue
        required = {s["skill_id"] for s in task["required_skills"]}
        covered = {
            skill["skill_id"]
            for assignee in task["assignees"]
            for skill in ctx["members"][assignee["member_id"]]["skills"]
        }
        if required - covered:
            affected.append(_recommend_or_reconsider(task["task_id"], leaving_member_id=member_id))
    return affected


def required_skill_added(task_id, skill_id):
    """Find an additional assignee when a newly required skill is uncovered."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if not _active(task):
        return None
    required = {s["skill_id"] for s in task["required_skills"]}
    if skill_id not in required:
        raise ValueError("The task does not currently require this skill.")
    covered = {
        skill["skill_id"]
        for assignee in task["assignees"]
        for skill in ctx["members"][assignee["member_id"]]["skills"]
    }
    return _recommend_or_reconsider(task_id) if required - covered else None


def task_required_skills_changed(task_id):
    """Reassess pending decisions or uncovered tasks after requirements change."""
    ctx = context.load_context()
    task = _task(ctx, task_id)
    if not _active(task):
        return None
    existing = decisions.open_decision_for(task_id)
    if existing:
        return service.reconsider_decision(existing["decision_id"])
    if not task["assignees"]:
        return service.recommend_task(task_id)
    required = {skill["skill_id"] for skill in task["required_skills"]}
    covered = {
        skill["skill_id"]
        for assignee in task["assignees"]
        for skill in ctx["members"][assignee["member_id"]]["skills"]
    }
    return service.recommend_task(task_id) if required - covered else None


def member_skill_added(member_id, skill_id):
    """Revisit waiting or unassigned tasks when a member gains a skill."""
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if skill_id not in {skill["skill_id"] for skill in member["skills"]}:
        raise ValueError("The member does not currently have this skill.")
    results = []
    visited = set()
    for waiting in decisions.list_pending():
        task = ctx["tasks"].get(waiting["task_id"])
        if not _active(task) or skill_id not in {s["skill_id"] for s in task["required_skills"]}:
            continue
        leaving_id = waiting.get("leaving_member_id")
        eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"], leaving_id)
        if _ready(ctx, task) and member_id in {candidate["member_id"] for candidate in eligible}:
            results.append(service.reconsider_decision(waiting["decision_id"]))
            visited.add(task["task_id"])
    for task in ctx["tasks"].values():
        if task["task_id"] in visited or not _active(task) or task["assignees"]:
            continue
        if skill_id in {s["skill_id"] for s in task["required_skills"]} and _ready(ctx, task):
            eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"])
            if member_id in {candidate["member_id"] for candidate in eligible}:
                results.append(_recommend_or_reconsider(task["task_id"]))
    return results


def member_skill_added(member_id, skill_id):
    """Revisit work when an available member gains a required skill."""
    ctx = context.load_context()
    member = ctx["members"].get(member_id)
    if member is None:
        raise ValueError("Member ID does not exist.")
    if skill_id not in {skill["skill_id"] for skill in member["skills"]}:
        raise ValueError("The member does not currently have this skill.")
    if not member["available"]:
        return []

    results, revisited = [], set()
    for waiting in decisions.list_pending():
        task = ctx["tasks"].get(waiting["task_id"])
        if not _active(task) or skill_id not in {s["skill_id"] for s in task["required_skills"]}:
            continue
        leaving_id = waiting.get("leaving_member_id")
        eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"], leaving_id)
        if _ready(ctx, task) and member_id in {candidate["member_id"] for candidate in eligible}:
            results.append(service.reconsider_decision(waiting["decision_id"]))
            revisited.add(task["task_id"])

    for task in ctx["tasks"].values():
        if task["task_id"] in revisited or not _active(task) or task["assignees"]:
            continue
        if skill_id not in {s["skill_id"] for s in task["required_skills"]} or not _ready(ctx, task):
            continue
        eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"])
        if member_id in {candidate["member_id"] for candidate in eligible}:
            results.append(_recommend_or_reconsider(task["task_id"]))
    return results


def run_scheduled_sweep():
    """Expire unanswered decisions, wake feasible waits, and surface risk tasks."""
    expired = decisions.expire_older_than()
    ctx = context.load_context()
    generated = {}
    at_risk = set()

    for waiting in decisions.list_pending(action="wait"):
        task = ctx["tasks"].get(waiting["task_id"])
        if not _active(task):
            decisions.set_status(waiting["decision_id"], "stale", note="Task is complete or no longer exists.")
            continue
        leaving_id = waiting.get("leaving_member_id")
        if leaving_id is not None and leaving_id not in {a["member_id"] for a in task["assignees"]}:
            decisions.set_status(waiting["decision_id"], "stale", note="The task assignment changed while waiting.")
            continue
        eligible, _rejected, _gap = eligible_candidates(ctx, task["task_id"], leaving_id)
        if _ready(ctx, task) and eligible:
            decision = service.reconsider_decision(waiting["decision_id"])
            generated[decision["decision_id"]] = decision

    for task in ctx["tasks"].values():
        if not _active(task):
            continue
        if not task["assignees"]:
            decision = task_became_unassigned(task["task_id"])
            if decision is not None:
                generated[decision["decision_id"]] = decision
        if task["slack"] <= 0:
            at_risk.add(task["task_id"])
            decision = task_slack_exhausted(task["task_id"])
            if decision is not None:
                generated[decision["decision_id"]] = decision

    for member in ctx["members"].values():
        if member["available"]:
            for decision in member_became_overloaded(member["member_id"]):
                generated[decision["decision_id"]] = decision

    learning.refresh_thresholds()
    return {"expired": expired, "decisions": list(generated.values()), "at_risk_task_ids": sorted(at_risk)}
