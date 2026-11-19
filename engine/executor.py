
from db_operations import update
from engine.config import STATUS_COMPLETE


def make_plan(task_id, leaving_member_id, new_member_id):
    if leaving_member_id is None:
        return [{"op": "assign", "task_id": task_id, "member_id": new_member_id}]
    return [{"op": "reassign", "task_id": task_id, "from": leaving_member_id, "to": new_member_id}]


def _run(step, decision_id):
    op = step["op"]
    if op == "reassign":
        update.reassign_member(step["task_id"], step["from"], step["to"], decision_id=decision_id)
    elif op == "assign":
        update.assign_member(step["task_id"], step["member_id"], decision_id=decision_id)
    elif op == "unassign":
        update.unassign_member(step["task_id"], step["member_id"], decision_id=decision_id)
    else:
        raise ValueError(f"Unknown operation: {op}")


def invert(plan):
    inverse = []
    for step in reversed(plan):
        if step["op"] == "reassign":
            inverse.append({"op": "reassign", "task_id": step["task_id"],
                            "from": step["to"], "to": step["from"]})
        elif step["op"] == "assign":
            inverse.append({"op": "unassign", "task_id": step["task_id"], "member_id": step["member_id"]})
        elif step["op"] == "unassign":
            inverse.append({"op": "assign", "task_id": step["task_id"], "member_id": step["member_id"]})
        else:
            raise ValueError(f"Unknown operation: {step['op']}")
    return inverse


def execute(plan, decision_id=None):
    applied = []
    try:
        for step in plan:
            _run(step, decision_id)
            applied.append(step)
    except Exception:
        for undo_step in invert(applied):
            _run(undo_step, decision_id)
        raise
    return applied


def can_apply(plan, ctx):
    for step in plan:
        task = ctx["tasks"].get(step["task_id"])
        if task is None or task["status"] == STATUS_COMPLETE:
            return False
        assigned = {a["member_id"] for a in task["assignees"]}
        if step["op"] == "reassign":
            if step["from"] not in assigned or step["to"] in assigned or step["to"] not in ctx["members"]:
                return False
        elif step["op"] == "assign":
            if step["member_id"] in assigned or step["member_id"] not in ctx["members"]:
                return False
        elif step["op"] == "unassign":
            if step["member_id"] not in assigned:
                return False
        else:
            return False
    return True