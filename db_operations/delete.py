from db import get_connection
import sqlite3
from db_operations.helpers import _check_int, _recalculate_workload, _log_history

def delete_member(member_id):
    _check_int(member_id, "Member ID")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(member_id,)).fetchone() is None:
                raise ValueError("Member ID does not exist.")
            held = conn.execute("SELECT COUNT(*) AS n FROM task_assignments WHERE member_id = ?",(member_id,)).fetchone()["n"]
            if held>0:
                raise ValueError(f"Member is still assigned to {held} tasks. Reassign or unassign.")
            conn.execute("DELETE FROM team_members WHERE member_id = ?",(member_id,))
            return True
    finally:
        conn.close()

def delete_skill(skill_id):
    _check_int(skill_id, "Skill ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM skills WHERE skill_id = ?",(skill_id,))
            if cursor.rowcount == 0:
                raise ValueError("Skill ID does not exist.")
            return True
    except sqlite3.IntegrityError as e:
        raise ValueError("Skill is still required by some entities.") from e
    finally:
        conn.close()

def delete_status(status_id):
    _check_int(status_id, "Status ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("SELECT definition FROM status WHERE status_id = ?",(status_id,)).fetchone()
            if cursor is None:
                raise ValueError("Status ID does not exist.")
            if status_id == 1 or cursor["definition"] == "Complete":
                raise ValueError("The default (Pending) and Complete statuses cannot be deleted.")
            conn.execute("DELETE FROM status WHERE status_id = ?",(status_id,))
            return True
    except sqlite3.IntegrityError as e:
        raise ValueError("Status is still used by one or more entities.") from e
    finally:
        conn.close()

def delete_task(task_id):
    _check_int(task_id, "Task ID")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            members = [r["member_id"] for r in conn.execute("SELECT member_id FROM task_assignments WHERE task_id = ? ",(task_id,)).fetchall()]
            conn.execute("DELETE FROM tasks WHERE task_id = ?",(task_id,))
            for member_id in members:
                _recalculate_workload(conn,member_id)
            return True
    finally:
        conn.close()

def delete_member_skill(member_id, skill_id):
    _check_int(member_id, "Member ID")
    _check_int(skill_id, "Skill ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM members_skills WHERE member_id = ? AND skill_id = ?",(member_id, skill_id,))
            return cursor.rowcount == 1
    finally:
        conn.close()

def delete_required_skill(skill_id, task_id):
    _check_int(skill_id, "Skill ID")
    _check_int(task_id, "Task ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM required_skills WHERE skill_id = ? AND task_id = ?",(skill_id, task_id,))
            return cursor.rowcount == 1
    finally:
        conn.close()

def delete_dependency(dependency_id):
    _check_int(dependency_id, "Dependency ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM dependencies WHERE dependency_id = ?",(dependency_id,))
            if cursor.rowcount == 0:
                raise ValueError("Dependency ID does not exist.")
            return True
    finally:
        conn.close()

def unassign_task(task_id,member_id):
    _check_int(task_id, "Task ID")
    _check_int(member_id, "Assignee ID")
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
                raise ValueError("Task ID does not exist.")
            if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(member_id,)).fetchone() is None:
                raise ValueError("Assignee ID does not exist.")
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ? ",(member_id, task_id,)).fetchone() is None:
                raise ValueError("Member is not assigned to this task.")
            conn.execute("DELETE FROM task_assignments WHERE task_id = ? AND member_id = ?",(task_id,member_id,))
            change_id = _log_history(conn, action="unassigned",assignee_id=member_id, task_id=task_id)
            _recalculate_workload(conn,member_id)
            return change_id
    finally:
        conn.close()