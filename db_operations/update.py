from db import get_connection
import sqlite3
from db_operations.helpers import _check_string, _check_int, _recalculate_workload, _log_history,_recalculate_task_workloads

def update_member_name(member_id, name):
    _check_int(member_id, "Member ID")
    name = _check_string(name, "Member name")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE team_members SET name = ? WHERE member_id = ?",(name,member_id,))
            if cursor.rowcount == 0:
                raise ValueError("Member ID does not exist.")
            return True
    finally:
        conn.close()

def update_member_availability(member_id, available):
    _check_int(member_id, "Member ID")
    if available is None:
        raise ValueError("Availability cannot be empty.")
    if not isinstance(available, bool):
        raise ValueError("Availability has to be of boolean type.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE team_members SET available = ? WHERE member_id = ?",(available,member_id,))
            if cursor.rowcount == 0:
                raise ValueError("Member ID does not exist.")
            return True
    finally:
        conn.close()

def update_member_role(member_id, role):
    """Set whether a member is a team lead who can approve proposals."""
    _check_int(member_id, "Member ID")
    if not isinstance(role, bool):
        raise ValueError("Role must be a boolean value.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE team_members SET role = ? WHERE member_id = ?", (role, member_id))
            if cursor.rowcount == 0:
                raise ValueError("Member ID does not exist.")
            return True
    finally:
        conn.close()

def update_skill(skill_id, name):
    _check_int(skill_id, "Skill ID")
    name = _check_string(name, "Skill name")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE skills SET name = ? WHERE skill_id = ?", (name, skill_id,))
            if cursor.rowcount == 0:
                raise ValueError("Skill ID does not exist.")
            return True
    except sqlite3.IntegrityError as e:
        raise ValueError("Skill already exists.") from e
    finally:
        conn.close()

def update_status(status_id, definition):
    _check_int(status_id, "Status ID")
    definition = _check_string(definition, "Status Definition")
    conn = get_connection()
    try:
        with conn:
            row = conn.execute("SELECT definition FROM status WHERE status_id = ?", (status_id,)).fetchone()
            if row is None:
                raise ValueError("Status ID does not exist.")
            if row["definition"] == "Complete" and definition != "Complete":
                raise ValueError("'Complete' is used in workload calculations and cannot be renamed.")
            conn.execute("UPDATE status SET definition = ? WHERE status_id = ?", (definition, status_id))
            return True
    except sqlite3.IntegrityError as e:
        raise ValueError("Status definition already exists.") from e
    finally:
        conn.close()

def update_task_name(task_id, name):
    _check_int(task_id, "Task ID")
    name = _check_string(name, "Task name")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE tasks SET name = ? WHERE task_id = ?", (name, task_id,))
            if cursor.rowcount == 0:
                raise ValueError("Task ID does not exist.")
            return True
    finally:
        conn.close()

def update_task_duration(task_id, duration):
    _check_int(task_id, "Task ID")
    _check_int(duration, "Duration")
    if duration<=0:
        raise ValueError("Duration cannot be zero or a negative value.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE tasks SET duration = ? WHERE task_id = ?",(duration,task_id,))
            if cursor.rowcount == 0:
                raise ValueError("Task ID does not exist.")
            _recalculate_task_workloads(conn, task_id)
            return True
    finally:
        conn.close()

def update_task_priority(task_id, priority):
    _check_int(task_id, "Task ID")
    _check_int(priority, "Priority")
    if priority<0 or priority>5:
        raise ValueError("Priority must lie between 0-5.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE tasks SET priority = ? WHERE task_id = ?",(priority,task_id,))
            if cursor.rowcount == 0:
                raise ValueError("Task ID does not exist.")
            return True
    finally:
        conn.close()

def update_task_slack(task_id, slack):
    _check_int(task_id, "Task ID")
    _check_int(slack, "Slack")
    if slack<0:
        raise ValueError("Slack cannot be a negative value.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("UPDATE tasks SET slack = ? WHERE task_id = ?",(slack,task_id,))
            if cursor.rowcount == 0:
                raise ValueError("Task ID does not exist.")
            return True
    finally:
        conn.close()

def update_task_status(task_id, new_status_id):
    _check_int(task_id, "Task ID")
    _check_int(new_status_id, "New Status ID")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("SELECT status_id FROM tasks WHERE task_id = ?",(task_id,)).fetchone()
            if cursor is None:
                raise ValueError("Task ID does not exist.")
            old_status_id = cursor["status_id"]
            if(old_status_id == new_status_id) :
                raise ValueError("Status unchanged.")
            if conn.execute("SELECT 1 FROM status WHERE status_id = ?",(new_status_id,)).fetchone() is None:
                raise ValueError("New status id does not exist.")
            conn.execute("UPDATE tasks SET status_id = ? WHERE task_id = ?",(new_status_id, task_id,))
            _recalculate_task_workloads(conn, task_id)
            return True
    finally:
        conn.close()

def assign_member(task_id, member_id, decision_id=None):
    _check_int(task_id, "Task ID")
    _check_int(member_id, "Assignee ID")
    _check_int(decision_id, "Decision ID", allow_none=True)
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?", (member_id,)).fetchone() is None:
                raise ValueError("Assignee ID does not exist.")
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ?", (member_id, task_id)).fetchone():
                raise ValueError("Member already assigned to this task.")
            conn.execute("INSERT INTO task_assignments (member_id, task_id) VALUES (?,?)", (member_id, task_id))
            change_id = _log_history(conn, action="assigned", assignee_id=member_id, task_id=task_id, decision_id=decision_id)
            _recalculate_workload(conn, member_id)
            return change_id
    finally:
        conn.close()


def unassign_member(task_id, member_id, decision_id=None):
    _check_int(task_id, "Task ID")
    _check_int(member_id, "Assignee ID")
    _check_int(decision_id, "Decision ID", allow_none=True)
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?", (member_id,)).fetchone() is None:
                raise ValueError("Assignee ID does not exist.")
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ?", (member_id, task_id)).fetchone() is None:
                raise ValueError("Member is not assigned to this task.")
            conn.execute("DELETE FROM task_assignments WHERE task_id = ? AND member_id = ?", (task_id, member_id))
            change_id = _log_history(conn, action="unassigned", assignee_id=member_id, task_id=task_id, decision_id=decision_id)
            _recalculate_workload(conn, member_id)
            return change_id
    finally:
        conn.close()


def reassign_task(task_id, old_member_id, new_member_id, decision_id=None):
    _check_int(task_id, "Task ID")
    _check_int(old_member_id, "Old Member ID")
    _check_int(new_member_id, "New Member ID")
    _check_int(decision_id, "Decision ID", allow_none=True)
    if old_member_id == new_member_id:
        raise ValueError("Both members are the same. No change.")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(old_member_id,)).fetchone() is None:
                raise ValueError("Old Member ID does not exist.")
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ?",(old_member_id, task_id,)).fetchone() is None:
                raise ValueError("Old member not assigned to this task.")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(new_member_id,)).fetchone() is None:
                raise ValueError("New Member ID does not exist.")
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ?",(new_member_id, task_id,)).fetchone():
                raise ValueError("New member already assigned to this task.")
            conn.execute("DELETE FROM task_assignments WHERE member_id = ? AND task_id = ?",(old_member_id, task_id,))
            out_id = _log_history(conn, action="unassigned", assignee_id=old_member_id, task_id=task_id, decision_id=decision_id)
            conn.execute("INSERT INTO task_assignments (member_id, task_id) VALUES (?,?)",(new_member_id, task_id))
            in_id = _log_history(conn, action="assigned", assignee_id=new_member_id, task_id=task_id, decision_id=decision_id)
            _recalculate_workload(conn, old_member_id)
            _recalculate_workload(conn, new_member_id)
            return (out_id, in_id)
    finally:
        conn.close()

def reassign_member(task_id, old_member_id, new_member_id, decision_id=None):
    return reassign_task(task_id, old_member_id, new_member_id, decision_id=decision_id)


def update_task_required_skills(task_id, skill_ids):
    """Replace a task's required skills atomically and report what changed."""
    _check_int(task_id, "Task ID")
    if not isinstance(skill_ids, (list, tuple, set)):
        raise ValueError("Required skill IDs must be a list of skill IDs.")
    requested = []
    for value in skill_ids:
        _check_int(value, "Skill ID")
        if value not in requested:
            requested.append(value)
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            existing = {row["skill_id"] for row in conn.execute(
                "SELECT skill_id FROM required_skills WHERE task_id = ?", (task_id,)).fetchall()}
            if requested:
                marks = ",".join("?" for _ in requested)
                found = {row["skill_id"] for row in conn.execute(
                    f"SELECT skill_id FROM skills WHERE skill_id IN ({marks})", requested).fetchall()}
                missing = set(requested) - found
                if missing:
                    raise ValueError(f"Skill ID does not exist: {min(missing)}.")
            added, removed = set(requested) - existing, existing - set(requested)
            conn.execute("DELETE FROM required_skills WHERE task_id = ?", (task_id,))
            conn.executemany("INSERT INTO required_skills (task_id, skill_id) VALUES (?, ?)",
                             [(task_id, skill_id) for skill_id in requested])
            return {"added": sorted(added), "removed": sorted(removed)}
    finally:
        conn.close()
