from db import get_connection
import sqlite3
from db_operations.helpers import _check_int, _check_string, _recalculate_workload,_log_history

def add_skill(name):
    #Add a new row in the skills table
    name = _check_string(name,"Skill Name")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO skills(name) VALUES (?)", (name,))
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Skill name '{name}' already exists.") from e
    finally:
        conn.close()

def add_member(name, workload, available, role=False):
    #Add a new team member
    name = _check_string(name, "Member Name")
    _check_int(workload, "Workload")
    if workload<0:
        raise ValueError("Workload cannot be a negative value.")
    if available is None:
        raise ValueError("Availability cannot be null.")
    if not isinstance(available, bool):
        raise ValueError("Availability has to be a boolean value.")
    if role is None:
            raise ValueError("Role cannot be null.")
    if not isinstance(role, bool):
            raise ValueError("Role has to be a boolean value.")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO team_members(available, name, workload, role) VALUES (?,?,?,?)", (available, name, workload,role,))
            return cursor.lastrowid
    finally:
        conn.close()

def add_status(definition):
    #Add a new status definition.
    definition = _check_string(definition,"Status Definition")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO status (definition) VALUES (?)",(definition,))
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Status definition '{definition}' already exists.") from e
    finally:
        conn.close()

def add_member_skill(member_id, skill_id):
    _check_int(member_id, "Member ID")
    _check_int(skill_id, "Skill ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT OR IGNORE INTO members_skills (member_id, skill_id) VALUES (?,?)",(member_id, skill_id,))
            return cursor.rowcount==1
    except sqlite3.IntegrityError as e:
        if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(member_id,)).fetchone() is None:
            raise ValueError("Member does not exist.") from e
        if conn.execute("SELECT 1 FROM skills WHERE skill_id = ?",(skill_id,)).fetchone() is None:
            raise ValueError("Skill does not exist.") from e
        raise
    finally:
        conn.close()

def add_task(duration, name, priority, slack, status_id):
    _check_int(duration, "Duration")
    if duration<=0:
        raise ValueError("Duration cannot be zero or negative.")
    name = _check_string(name, "Task name")
    _check_int(priority, "Priority")
    if priority<0 or priority>5:
        raise ValueError("Priority must lie from 0-5.")
    _check_int(slack, "Slack")
    if slack<0:
        raise ValueError("Slack cannot be negative.")
    _check_int(status_id, "Status ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO tasks (duration, name, priority, slack, status_id) VALUES (?,?,?,?,?)",(duration, name, priority, slack, status_id,))
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        if conn.execute("SELECT 1 FROM status WHERE status_id = ?",(status_id,)).fetchone() is None:
            raise ValueError("Status does not exist.") from e
        raise
    finally:
        conn.close()

def assign_task(task_id, member_id):
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
            if conn.execute("SELECT 1 FROM task_assignments WHERE member_id = ? AND task_id = ? ",(member_id, task_id,)).fetchone():
                raise ValueError("Member already assigned to this task.")
            conn.execute("INSERT INTO task_assignments (member_id, task_id) VALUES (?,?)",(member_id, task_id,))
            change_id = _log_history(conn, action="assigned",assignee_id=member_id, task_id=task_id)
            _recalculate_workload(conn,member_id)
            return change_id
    finally:
        conn.close()

def add_dependency(predecessor_id, task_id):
    _check_int(predecessor_id, "Predecessor ID")
    _check_int(task_id, "Task ID")
    if predecessor_id == task_id:
        raise ValueError("Predecessor cannot be the same as the concerned task.")
    conn = get_connection()
    try:
        with conn:
            cycle = conn.execute("""
                WITH RECURSIVE ancestors(id) AS (
                SELECT predecessor_id FROM dependencies WHERE task_id = ?
                UNION
                SELECT d.predecessor_id FROM dependencies d JOIN ancestors a ON d.task_id = a.id
                )
                SELECT 1 FROM ancestors WHERE id = ? LIMIT 1
            """, (predecessor_id, task_id)).fetchone()
            if cycle:
                raise ValueError("This dependency would create a circular chain.")
            cursor = conn.execute("INSERT INTO dependencies (predecessor_id, task_id) VALUES (?,?)",(predecessor_id, task_id,))
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(predecessor_id,)).fetchone() is None:
            raise ValueError("Task(Predecessor) does not exist.") from e
        if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
            raise ValueError("Task does not exist.") from e
        raise ValueError("This dependency already exists.")
    finally:
        conn.close()

def add_required_skill(skill_id, task_id):
    _check_int(skill_id, "Skill ID")
    _check_int(task_id, "Task ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT OR IGNORE INTO required_skills (skill_id, task_id) VALUES (?,?)",(skill_id, task_id,))
            return cursor.rowcount==1
    except sqlite3.IntegrityError as e:
        if conn.execute("SELECT 1 FROM skills WHERE skill_id = ?",(skill_id,)).fetchone() is None:
            raise ValueError("Skill does not exist.") from e
        if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
            raise ValueError("Task does not exist.") from e
        raise
    finally:
        conn.close()

def add_history(action, assignee_id, task_id):
    action = _check_string(action,"Action")
    if action not in ("assigned", "unassigned"):
        raise ValueError("Action can be either 'assigned' or 'unassigned'.")
    _check_int(assignee_id, "Assignee ID")
    _check_int(task_id, "Task ID")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO history (action, assignee_id, task_id) VALUES (?,?,?)",(action, assignee_id, task_id,))
            return cursor.rowcount==1
    except sqlite3.IntegrityError as e:
        if conn.execute("SELECT 1 FROM team_members WHERE member_id = ?",(assignee_id,)).fetchone() is None:
            raise ValueError("Assignee ID does not exist.") from e
        if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",(task_id,)).fetchone() is None:
            raise ValueError("Task does not exist.") from e
        raise
    finally:
        conn.close()