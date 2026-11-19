from db import get_connection

def get_all_skills():
    #Return all available skills.
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT skill_id,name FROM skills ORDER BY NAME"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_all_members():
    #Return all the team members.
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT member_id, name, available, workload, role FROM team_members ORDER BY NAME"
        ).fetchall()
        result = []
        #Retrieve skills of each member.
        for member in rows:
            skills = conn.execute("""
                SELECT s.skill_id, s.name FROM skills s
                JOIN members_skills ms ON s.skill_id = ms.skill_id
                WHERE ms.member_id = ?
                ORDER BY s.name
            """,(member["member_id"],)).fetchall()
            member_data = dict(member)
            member_data["skills"] = [
                dict(skill) for skill in skills
            ]
            result.append(member_data)
        return result
    finally:
        conn.close()

def get_all_tasks():
    #Return all tasks.
    conn = get_connection()
    try:
        tasks = conn.execute("""
            SELECT t.task_id, t.duration, t.name, t.priority, t.slack, t.status_id, s.definition AS status
            FROM tasks t
            JOIN status s ON s.status_id = t.status_id
            ORDER BY t.name
        """).fetchall()
        result = []

        for task in tasks:
            task_data = dict(task)
            task_id = task["task_id"]

            #Retrieve required skills for each task.
            skills = conn.execute("""
                SELECT s.skill_id, s.name
                FROM skills s
                JOIN required_skills rs ON rs.skill_id = s.skill_id
                WHERE rs.task_id = ?
                ORDER BY s.name
            """,(task_id,)).fetchall()

            #Retrieve dependencies of each task.
            dependencies = conn.execute("""
                SELECT d.predecessor_id, t.name as predecessor_name
                FROM dependencies d
                JOIN tasks t ON t.task_id = d.predecessor_id
                WHERE d.task_id = ?
            """, (task_id,)).fetchall()

            #Retrieve task assignments
            assignments = conn.execute("""
                SELECT ta.assignment_id, tm.member_id, tm.name
                FROM task_assignments ta
                JOIN team_members tm ON tm.member_id = ta.member_id
                WHERE ta.task_id = ?
                ORDER BY tm.name 
            """,(task_id,)).fetchall()

            task_data["required_skills"] = [
                dict(skill) for skill in skills
            ]
            task_data["dependencies"] = [
                dict(d) for d in dependencies
            ]
            assignee_data = [dict(assignment) for assignment in assignments]
            task_data["assignees"] = assignee_data
            # Keep the original database API key for callers that already use it.
            task_data["assignments"] = assignee_data
            result.append(task_data)

        return result
    finally:
        conn.close()

def get_all_history():
    #Retrieve complete history log.
    conn = get_connection()
    try:
        logs = conn.execute("""
            SELECT h.change_id, h.action, h.created_at, h.assignee_id, tm.name AS assignee_name, h.task_id, h.decision_id, t.name as task_name
            FROM history h
            JOIN tasks t ON t.task_id = h.task_id
            LEFT JOIN team_members tm ON tm.member_id = h.assignee_id
            ORDER BY h.created_at DESC, h.change_id DESC
        """).fetchall()
        return [dict(log) for log in logs]
    finally:
        conn.close()

def get_all_dependencies():
    #Retrieve all dependencies
    conn = get_connection()
    try:
        dependencies = conn.execute("""
            SELECT d.dependency_id, d.predecessor_id, p.name as predecessor_name, d.task_id, t.name as task_name
            FROM dependencies d
            JOIN tasks p ON p.task_id = d.predecessor_id
            JOIN tasks t ON t.task_id = d.task_id
            ORDER BY d.dependency_id
        """).fetchall()
        return [dict(dependency) for dependency in dependencies]
    finally:
        conn.close()

def get_all_statuses():
    #Retrieve all statuses
    conn = get_connection()
    try:
        statuses = conn.execute("""
            SELECT * FROM status
            ORDER BY status_id
        """).fetchall()
        return [dict(status) for status in statuses]
    finally:
        conn.close()

def get_task_history(task_id):
    #Retrieve history log of selected task.
    conn = get_connection()
    try:
        logs = conn.execute("""
            SELECT h.change_id, h.action, h.created_at, h.assignee_id, tm.name AS assignee_name, h.task_id, h.decision_id
            FROM history h
            LEFT JOIN team_members tm ON tm.member_id = h.assignee_id
            WHERE  h.task_id = ?
            ORDER BY h.created_at DESC, h.change_id DESC
        """,(task_id,)).fetchall()

        return [dict(log) for log in logs]
    finally:
        conn.close()