import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_DIR = PROJECT_DIR / 'database'
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / 'allocation.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def initialise_database():
    conn = get_connection()
    cursor = conn.cursor()

    #Skills
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)

    #Team
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            available BOOLEAN NOT NULL DEFAULT 1,
            workload INTEGER NOT NULL DEFAULT 0 CHECK(workload>=0),
            role BOOLEAN NOT NULL
        )
    """)

    #Members Skill
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS members_skills (
            member_id INTEGER NOT NULL,
            skill_id INTEGER NOT NULL,
            PRIMARY KEY(member_id, skill_id),
            FOREIGN KEY(member_id)
                REFERENCES team_members(member_id) ON DELETE CASCADE,
            FOREIGN KEY(skill_id)
                REFERENCES skills(skill_id) ON DELETE CASCADE
        )
    """)

    #Status
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status (
            status_id INTEGER PRIMARY KEY AUTOINCREMENT,
            definition TEXT NOT NULL UNIQUE
        )
    """)
    cursor.executemany(
        "INSERT OR IGNORE INTO status (definition) values (?)",
        [('Pending',),('In Progress',),('Complete',)]
    )

    #Tasks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration INTEGER NOT NULL CHECK (duration>0),
            status_id INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 5,
            slack INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(status_id)
                REFERENCES status(status_id) ON DELETE RESTRICT,
            CHECK(priority>-1 AND priority<6)
        )
    """)

    #Member assignment for each task
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_assignments(
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            FOREIGN KEY(task_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY(member_id)
                REFERENCES team_members(member_id) ON DELETE RESTRICT,
            UNIQUE(task_id, member_id)
        )
    """)

    #Required skill for the tasks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS required_skills (
            task_id INTEGER NOT NULL,
            skill_id INTEGER NOT NULL,
            PRIMARY KEY(task_id,skill_id),
            FOREIGN KEY(task_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY(skill_id)
                REFERENCES skills(skill_id) ON DELETE RESTRICT
        )
    """)

    #Task dependencies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dependencies (
            dependency_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            predecessor_id INTEGER NOT NULL,
            FOREIGN KEY(task_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY(predecessor_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            UNIQUE(task_id, predecessor_id),
            CHECK(task_id!=predecessor_id)
        )
    """)

    #Record of history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            change_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            assignee_id INTEGER,
            action TEXT NOT NULL CHECK(action IN ('assigned','unassigned')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            decision_id INTEGER,
            FOREIGN KEY(task_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY(assignee_id)
                REFERENCES team_members(member_id) ON DELETE SET NULL,
            FOREIGN KEY(decision_id)
                REFERENCES decisions(decision_id) ON DELETE SET NULL
        )
    """)

    #Decision table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            leaving_member_id INTEGER,
            member_id INTEGER,
            action TEXT NOT NULL CHECK(action IN ('propose','ask','wait','auto')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','expired','executed_auto','undone','stale')),
            plan TEXT,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            factors TEXT,
            detail TEXT,
            approver_id INTEGER,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY(task_id)
                REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY(leaving_member_id)
                REFERENCES team_members(member_id) ON DELETE SET NULL,
            FOREIGN KEY(member_id)
                REFERENCES team_members(member_id) ON DELETE SET NULL,
            FOREIGN KEY(approver_id)
                REFERENCES team_members(member_id) ON DELETE SET NULL
        )
    """)

    #Learned weights and thresholds
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS engine_settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    decision_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(decisions)")}
    decision_table = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'"
    ).fetchone()
    decision_sql = (decision_table["sql"] or "").lower() if decision_table else ""
    required_decision_columns = {
        "decision_id", "task_id", "leaving_member_id", "member_id", "action", "status",
        "plan", "confidence", "reason", "factors", "detail", "approver_id", "note",
        "created_at", "resolved_at",
    }
    allowed_decision_values = (
        "'propose'", "'ask'", "'wait'", "'auto'", "'pending'", "'approved'",
        "'rejected'", "'expired'", "'executed_auto'", "'undone'", "'stale'",
    )
    rebuild_decisions = (
        required_decision_columns - decision_columns
        or any(value not in decision_sql for value in allowed_decision_values)
    )
    if rebuild_decisions:
        conn.commit()
        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DROP TABLE IF EXISTS decisions_new")
            cursor.execute("""
                CREATE TABLE decisions_new (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    leaving_member_id INTEGER,
                    member_id INTEGER,
                    action TEXT NOT NULL CHECK(action IN ('propose','ask','wait','auto')),
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','expired','executed_auto','undone','stale')),
                    plan TEXT,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    factors TEXT,
                    detail TEXT,
                    approver_id INTEGER,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY(leaving_member_id) REFERENCES team_members(member_id) ON DELETE SET NULL,
                    FOREIGN KEY(member_id) REFERENCES team_members(member_id) ON DELETE SET NULL,
                    FOREIGN KEY(approver_id) REFERENCES team_members(member_id) ON DELETE SET NULL
                )
            """)
            old_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(decisions)")}
            decision_fields = (
                "decision_id", "task_id", "leaving_member_id", "member_id", "action", "status",
                "plan", "confidence", "reason", "factors", "detail", "approver_id", "note",
                "created_at", "resolved_at",
            )
            defaults = {"leaving_member_id": None, "member_id": None, "status": "pending",
                        "plan": None, "factors": None, "detail": None, "approver_id": None,
                        "note": None, "created_at": None, "resolved_at": None}
            old_rows = cursor.execute("SELECT * FROM decisions").fetchall()
            for old_row in old_rows:
                row = dict(old_row)
                values = {field: row[field] if field in old_columns else defaults.get(field)
                          for field in decision_fields}
                if values["status"] == "executed-auto":
                    values["status"] = "executed_auto"
                if values["action"] not in ("propose", "ask", "wait", "auto"):
                    raise RuntimeError(f"Cannot migrate decision {values['decision_id']}: unknown action.")
                if values["status"] not in ("pending", "approved", "rejected", "expired", "executed_auto", "undone", "stale"):
                    raise RuntimeError(f"Cannot migrate decision {values['decision_id']}: unknown status.")
                marks = ",".join("?" for _ in decision_fields)
                cursor.execute(
                    f"INSERT INTO decisions_new ({','.join(decision_fields)}) VALUES ({marks})",
                    tuple(values[field] for field in decision_fields),
                )
            cursor.execute("DROP TABLE decisions")
            cursor.execute("ALTER TABLE decisions_new RENAME TO decisions")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")

    history_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(history)")}
    if "decision_id" not in history_columns:
        cursor.execute("ALTER TABLE history ADD COLUMN decision_id INTEGER REFERENCES decisions(decision_id) ON DELETE SET NULL")

    decision_index = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_one_open_decision'"
    ).fetchone()
    decision_index_sql = (decision_index["sql"] or "").upper() if decision_index else ""
    if decision_index and ("UNIQUE" not in decision_index_sql or "COALESCE" not in decision_index_sql):
        duplicate = cursor.execute("""
            SELECT 1 FROM decisions
            WHERE status = 'pending'
            GROUP BY task_id, COALESCE(leaving_member_id, 0)
            HAVING COUNT(*) > 1
            LIMIT 1
        """).fetchone()
        if duplicate:
            raise RuntimeError("Cannot enforce one pending decision per task and leaving member while duplicates exist.")
        cursor.execute("DROP INDEX idx_one_open_decision")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_decision ON decisions(task_id, COALESCE(leaving_member_id, 0)) WHERE status = 'pending'")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_req_skills ON required_skills(skill_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deps_pred ON dependencies(predecessor_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_task ON history(task_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_assignments_member ON task_assignments(member_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_skill ON members_skills(skill_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status_id)")


    conn.commit()
    conn.close()

def seed_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM team_members")
    count = cursor.fetchone()[0]
    if(count>0):
        conn.close()
        return

    #Seed skills table
    skills_names = ['Python','Java','SQL','Frontend','Testing','DevOps']
    skill = {}
    for name in skills_names:
        cursor.execute("INSERT INTO skills (name) VALUES (?)", (name,))
        skill[name] = cursor.lastrowid

    #Seed team_members table
    members = [
        ('Aisha', 1, 6, ['Python', 'SQL'],0),
        ('Ben',   1, 4, ['Java', 'Testing'],0),
        ('Chen',  1, 8, ['SQL', 'Python'],1),
        ('Dana',  0, 0, ['Frontend'],0),             
        ('Eli',   1, 3, ['Testing', 'Python'],0),
        ('Farah', 1, 5, ['DevOps', 'Java'],0),
        ('Gabe',  1, 2, ['Python', 'Frontend'],0),   
    ]
    member = {}
    for name, available, workload, skills, role in members:
        cursor.execute("INSERT INTO team_members(name, available, workload, role) VALUES(?,?,?,?)", (name, available, workload, role),)
        member[name] = cursor.lastrowid
        cursor.executemany("INSERT INTO members_skills(member_id, skill_id) VALUES (?,?)",[(member[name],skill[s]) for s in skills],)

    #Seed tasks
    status = {
        row['definition']: row['status_id']
        for row in cursor.execute("SELECT status_id, definition FROM status")
    }
    tasks = [
        ('Design database schema', ['Chen'],          3, 'Complete',    2, 0, ['SQL']),
        ('Build REST API',         ['Aisha', 'Gabe'], 5, 'In Progress', 1, 0, ['Python']),
        ('Implement login backend',['Ben'],           4, 'In Progress', 2, 1, ['Java']),
        ('Build dashboard UI',     ['Dana', 'Gabe'],  6, 'In Progress', 3, 2, ['Frontend']),
        ('Write API tests',        ['Eli'],           3, 'Pending',     3, 2, ['Testing', 'Python']),
        ('Set up CI/CD pipeline',  ['Farah'],         4, 'Pending',     2, 1, ['DevOps']),
        ('Optimise queries',       [],                2, 'Pending',     4, 5, ['SQL']),
        ('Integration testing',    [],                3, 'Pending',     2, 0, ['Testing']),
    ]
    task = {}
    for name, assignees, duration, st, priority, slack, req in tasks:
        cursor.execute(
            "INSERT INTO tasks(name, duration, status_id, priority, slack) VALUES (?,?,?,?,?)",
            (name, duration, status[st], priority, slack),
        )
        task[name] = cursor.lastrowid
        cursor.executemany(
            "INSERT INTO required_skills(task_id, skill_id) VALUES (?,?)",
            [(task[name], skill[s]) for s in req],
        )
        cursor.executemany(
            "INSERT INTO task_assignments(task_id, member_id) VALUES (?,?)",
            [(task[name], member[m]) for m in assignees],
        )

    #Seed dependencies
    deps = [
        ('Build REST API',          'Design database schema'),
        ('Implement login backend', 'Design database schema'),
        ('Optimise queries',        'Design database schema'),
        ('Build dashboard UI',      'Build REST API'),
        ('Write API tests',         'Build REST API'),
        ('Integration testing',     'Write API tests'),
        ('Integration testing',     'Set up CI/CD pipeline'),
    ]
    cursor.executemany(
        "INSERT INTO dependencies (task_id, predecessor_id) VALUES (?, ?)",
        [(task[t], task[p]) for t, p in deps],
    )  


    #Seed history
    history = [
        ('Design database schema',  'Chen',  'assigned'),
        ('Build REST API',          'Aisha', 'assigned'),
        ('Build REST API',          'Gabe',  'assigned'),
        ('Build dashboard UI',      'Dana',  'assigned'),
        ('Build dashboard UI',      'Gabe',  'assigned'),
        ('Implement login backend', 'Gabe',  'assigned'),
        ('Implement login backend', 'Gabe',  'unassigned'),
        ('Implement login backend', 'Ben',   'assigned'),
    ]
    cursor.executemany(
        "INSERT INTO history (task_id, assignee_id, action) VALUES (?,?,?)",
        [(task[t], member[m], a) for t, m, a in history],
    )

    #Make the stored workloads match the assignments
    cursor.execute("""
        UPDATE team_members SET workload = (
            SELECT COALESCE(SUM(t.duration), 0)
            FROM task_assignments ta
            JOIN tasks t ON t.task_id = ta.task_id
            JOIN status s ON s.status_id = t.status_id
            WHERE ta.member_id = team_members.member_id AND s.definition != 'Complete'
        )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialise_database()
    seed_database()
    print("Database initialised successfully.")
