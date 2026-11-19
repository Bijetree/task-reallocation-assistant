from db_operations import retrieve
from engine.config import ROLE_LEAD, APPROVER_ROLES

_MEMBER_KEYS = {"member_id","name","workload","role","available","skills"}
_TASK_KEYS = {"task_id","name","duration","priority","status","slack","required_skills","dependencies","assignees"}

def _check_shape(rows, required, label, hint=""):
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"get_all_{label}() must return {sorted(missing)} for every row. {hint}".strip())

def load_context():
    members = retrieve.get_all_members()
    tasks = retrieve.get_all_tasks()
    _check_shape(members, _MEMBER_KEYS, "members")
    _check_shape(tasks, _TASK_KEYS, "tasks","Tasks have no assignee column.")
    return {
        "members": {m["member_id"]: m for m in members},
        "tasks": {t["task_id"]: t for t in tasks},
    }

def assignee_ids(task):
    return {
        a["member_id"] for a in task["assignees"]
    }

def skill_ids(member):
    return {
        s["skill_id"] for s in member["skills"]
    }
