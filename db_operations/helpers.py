#Int checking helper function
def _check_int(value, label, allow_none=False):
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{label} cannot be null.")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} has to be an integer value.")

#String checker helper function
def _check_string(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} cannot be empty.")
    return value

#Helper function for updating history.
def _log_history(conn, action, assignee_id, task_id, decision_id=None):
    cursor = conn.execute(
        "INSERT INTO history (action, assignee_id, task_id, decision_id) VALUES (?,?,?,?)",
        (action, assignee_id, task_id, decision_id),
    )
    return cursor.lastrowid
#Workload re-evaluating helper function
def _recalculate_workload(conn, member_id):
    conn.execute("""
        UPDATE team_members
        SET workload = (
            SELECT COALESCE(SUM(t.duration), 0)
            FROM task_assignments ta
            JOIN tasks t ON t.task_id = ta.task_id
            JOIN status s ON s.status_id = t.status_id
            WHERE ta.member_id = team_members.member_id AND s.definition != 'Complete'
        )
        WHERE member_id = ?
    """, (member_id,))

#Workload reevaluation of every member on a task
def _recalculate_task_workloads(conn, task_id):
    cursor = conn.execute("SELECT member_id FROM task_assignments WHERE task_id = ?",(task_id,)).fetchall()
    for c in cursor:
        _recalculate_workload(conn, c["member_id"])