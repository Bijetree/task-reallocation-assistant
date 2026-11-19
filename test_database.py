"""
Automated tester for the task-allocation database (db.py + db_operations/*).

Layout expected (run from the project root):
    db.py
    db_operations/{__init__.py, helpers.py, create.py, retrieve.py, update.py, delete.py}
    test_allocation.py

Run:  python test_allocation.py          (or: python -m unittest -v test_allocation)

Every test runs against a throw-away temp database, so your real
database/allocation.db is never touched.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from db_operations import create, delete, retrieve, update


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
class BaseCase(unittest.TestCase):
    seed = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = (db.DB_DIR, db.DB_PATH)
        db.DB_DIR = Path(self._tmp.name)
        db.DB_PATH = db.DB_DIR / "test.db"
        db.initialise_database()
        if self.seed:
            db.seed_database()

    def tearDown(self):
        db.DB_DIR, db.DB_PATH = self._old
        self._tmp.cleanup()

    # --- lookups -------------------------------------------------------- #
    def q(self, sql, params=()):
        conn = db.get_connection()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def one(self, sql, params=()):
        rows = self.q(sql, params)
        return rows[0][0] if rows else None

    def tid(self, name):
        return self.one("SELECT task_id FROM tasks WHERE name=?", (name,))

    def mid(self, name):
        return self.one("SELECT member_id FROM team_members WHERE name=?", (name,))

    def sid(self, name):
        return self.one("SELECT skill_id FROM skills WHERE name=?", (name,))

    def status_id(self, definition):
        return self.one("SELECT status_id FROM status WHERE definition=?", (definition,))

    def stored_workload(self, member_id):
        return self.one("SELECT workload FROM team_members WHERE member_id=?", (member_id,))

    def expected_workload(self, member_id):
        """Independent re-computation: sum of durations of non-Complete assigned tasks."""
        return self.one("""
            SELECT COALESCE(SUM(t.duration),0)
            FROM task_assignments ta
            JOIN tasks t ON t.task_id=ta.task_id
            JOIN status s ON s.status_id=t.status_id
            WHERE ta.member_id=? AND s.definition!='Complete'""", (member_id,))

    def assert_workloads_consistent(self):
        for r in self.q("SELECT member_id, name, workload FROM team_members"):
            self.assertEqual(
                r["workload"], self.expected_workload(r["member_id"]),
                f"Stored workload for {r['name']} does not match its assignments")


# --------------------------------------------------------------------------- #
# 1. Schema
# --------------------------------------------------------------------------- #
class TestSchema(BaseCase):
    seed = False

    def test_all_tables_exist(self):
        names = {r[0] for r in self.q("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ["skills", "team_members", "members_skills", "status", "tasks",
                  "task_assignments", "required_skills", "dependencies", "history", "decisions", "engine_settings"]:
            self.assertIn(t, names)

    def test_expected_columns(self):
        expected = {
            "skills": {"skill_id", "name"},
            "team_members": {"member_id", "name", "available", "workload", "role"},
            "members_skills": {"member_id", "skill_id"},
            "status": {"status_id", "definition"},
            "tasks": {"task_id", "name", "duration", "status_id", "priority", "slack"},
            "task_assignments": {"assignment_id", "task_id", "member_id"},
            "required_skills": {"task_id", "skill_id"},
            "dependencies": {"dependency_id", "task_id", "predecessor_id"},
            "decisions": {"decision_id", "task_id", "leaving_member_id", "member_id", "action", "status", "plan", "confidence", "reason", "factors", "detail", "approver_id", "note", "created_at", "resolved_at"},
            "engine_settings": {"key", "value"},
            "history": {"change_id", "task_id", "assignee_id", "action", "created_at", "decision_id"},
        }
        for table, cols in expected.items():
            got = {r["name"] for r in self.q(f"PRAGMA table_info({table})")}
            self.assertEqual(got, cols, f"Column mismatch in {table}")

    def test_default_statuses_seeded_in_order(self):
        rows = [r["definition"] for r in self.q("SELECT definition FROM status ORDER BY status_id")]
        self.assertEqual(rows, ["Pending", "In Progress", "Complete"])

    def test_initialise_is_idempotent(self):
        db.initialise_database()
        db.initialise_database()
        self.assertEqual(self.one("SELECT COUNT(*) FROM status"), 3)

    def test_initialise_starts_with_no_project_records(self):
        for table in ("skills", "team_members", "tasks", "task_assignments", "required_skills",
                      "dependencies", "history", "decisions", "engine_settings"):
            with self.subTest(table=table):
                self.assertEqual(self.one(f"SELECT COUNT(*) FROM {table}"), 0)

    def test_foreign_keys_pragma_on(self):
        conn = db.get_connection()
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            conn.close()

    def test_expected_indexes_exist(self):
        idx = {r[0] for r in self.q("SELECT name FROM sqlite_master WHERE type='index'")}
        for name in ["idx_req_skills", "idx_deps_pred", "idx_history_task",
                     "idx_task_assignments_member", "idx_members_skill", "idx_tasks_status"]:
            self.assertIn(name, idx)

    def test_check_constraints(self):
        conn = db.get_connection()
        try:
            bad = [
                "INSERT INTO team_members(name, workload) VALUES('x', -1)",
                "INSERT INTO tasks(name, duration) VALUES('x', 0)",
                "INSERT INTO tasks(name, duration, priority) VALUES('x', 1, 6)",
                "INSERT INTO tasks(name, duration, priority) VALUES('x', 1, -1)",
                "INSERT INTO history(task_id, action) VALUES(1, 'bogus')",
            ]
            for sql in bad:
                with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                    conn.execute(sql)
        finally:
            conn.close()

    def test_self_dependency_rejected(self):
        t = create.add_task(1, "t", 1, 0, 1)
        conn = db.get_connection()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO dependencies(task_id, predecessor_id) VALUES(?,?)", (t, t))
        finally:
            conn.close()

    def test_fk_enforced_on_task_status(self):
        conn = db.get_connection()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO tasks(name, duration, status_id) VALUES('x',1,999)")
        finally:
            conn.close()

    def test_duplicate_assignment_rows_blocked_by_schema(self):
        """A database constraint prevents duplicate task and member assignment rows."""
        t = create.add_task(1, "t", 1, 0, 1)
        m = create.add_member("m", 0, True)
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO task_assignments(task_id, member_id) VALUES(?,?)", (t, m))
            with self.assertRaises(sqlite3.IntegrityError,
                                   msg="Schema allows the same member to be assigned to a task twice"):
                conn.execute("INSERT INTO task_assignments(task_id, member_id) VALUES(?,?)", (t, m))
        finally:
            conn.close()

    def test_member_id_column_has_a_declared_type(self):
        info = {r["name"]: r["type"] for r in self.q("PRAGMA table_info(task_assignments)")}
        self.assertTrue(info["member_id"], "task_assignments.member_id has no declared type (missing INTEGER)")


# --------------------------------------------------------------------------- #
# 2. Seed data
# --------------------------------------------------------------------------- #
class TestSeed(BaseCase):
    def test_counts(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM skills"), 6)
        self.assertEqual(self.one("SELECT COUNT(*) FROM team_members"), 7)
        self.assertEqual(self.one("SELECT COUNT(*) FROM tasks"), 8)
        self.assertEqual(self.one("SELECT COUNT(*) FROM dependencies"), 7)
        self.assertEqual(self.one("SELECT COUNT(*) FROM history"), 8)

    def test_seed_is_idempotent(self):
        db.seed_database()
        self.assertEqual(self.one("SELECT COUNT(*) FROM team_members"), 7)

    def test_seeded_workloads_match_assignments(self):
        self.assert_workloads_consistent()

    def test_seed_has_no_dependency_cycle(self):
        # try to close a loop on the seed graph: Integration testing -> Design schema
        with self.assertRaises(ValueError):
            create.add_dependency(self.tid("Integration testing"), self.tid("Design database schema"))


# --------------------------------------------------------------------------- #
# 3. create.py
# --------------------------------------------------------------------------- #
class TestCreate(BaseCase):
    def test_add_skill(self):
        sid = create.add_skill("  Rust  ")
        self.assertEqual(self.one("SELECT name FROM skills WHERE skill_id=?", (sid,)), "Rust")

    def test_add_skill_duplicate_and_blank(self):
        with self.assertRaises(ValueError):
            create.add_skill("Python")
        with self.assertRaises(ValueError):
            create.add_skill("   ")
        with self.assertRaises(ValueError):
            create.add_skill(123)

    def test_add_member_valid_and_invalid(self):
        mid = create.add_member("Zed", 0, True)
        self.assertEqual(self.one("SELECT available FROM team_members WHERE member_id=?", (mid,)), 1)
        for args in [("", 0, True), ("Z", -1, True), ("Z", "3", True),
                     ("Z", 0, None), ("Z", 0, 1), ("Z", True, True)]:
            with self.assertRaises(ValueError, msg=str(args)):
                create.add_member(*args)

    def test_add_status(self):
        sid = create.add_status("Blocked")
        self.assertIsInstance(sid, int)
        with self.assertRaises(ValueError):
            create.add_status("Blocked")

    def test_add_member_skill(self):
        m, s = create.add_member("Zed", 0, True), self.sid("DevOps")
        self.assertTrue(create.add_member_skill(m, s))
        self.assertFalse(create.add_member_skill(m, s))  # already there
        with self.assertRaises(ValueError):
            create.add_member_skill(9999, s)
        with self.assertRaises(ValueError):
            create.add_member_skill(m, 9999)

    def test_add_task_valid_and_invalid(self):
        t = create.add_task(3, "New", 2, 1, 1)
        self.assertEqual(self.one("SELECT name FROM tasks WHERE task_id=?", (t,)), "New")
        bad = [(0, "n", 1, 0, 1), (1, "", 1, 0, 1), (1, "n", 6, 0, 1), (1, "n", -1, 0, 1),
               (1, "n", 1, -1, 1), (1, "n", 1, 0, 999), (1.5, "n", 1, 0, 1), (True, "n", 1, 0, 1)]
        for args in bad:
            with self.assertRaises(ValueError, msg=str(args)):
                create.add_task(*args)

    def test_assign_task_updates_workload_and_history(self):
        t, m = self.tid("Optimise queries"), self.mid("Ben")
        before = self.stored_workload(m)
        change_id = create.assign_task(t, m)
        self.assertIsInstance(change_id, int)
        self.assertEqual(self.stored_workload(m), before + 2)
        self.assertEqual(self.one("SELECT action FROM history WHERE change_id=?", (change_id,)), "assigned")
        self.assert_workloads_consistent()

    def test_assign_task_errors(self):
        t, m = self.tid("Build REST API"), self.mid("Aisha")
        with self.assertRaises(ValueError):
            create.assign_task(t, m)           # duplicate
        with self.assertRaises(ValueError):
            create.assign_task(9999, m)
        with self.assertRaises(ValueError):
            create.assign_task(t, 9999)

    def test_add_dependency_ok_cycle_dup_missing(self):
        a, b, c = (create.add_task(1, n, 1, 0, 1) for n in "abc")
        create.add_dependency(a, b)             # b depends on a
        create.add_dependency(b, c)             # c depends on b
        with self.assertRaises(ValueError):
            create.add_dependency(c, a)         # a depends on c -> cycle
        with self.assertRaises(ValueError):
            create.add_dependency(a, b)         # duplicate
        with self.assertRaises(ValueError):
            create.add_dependency(a, a)         # self
        with self.assertRaises(ValueError):
            create.add_dependency(a, 9999)
        with self.assertRaises(ValueError):
            create.add_dependency(9999, a)

    def test_add_required_skill(self):
        t = create.add_task(1, "t", 1, 0, 1)
        self.assertTrue(create.add_required_skill(self.sid("SQL"), t))
        self.assertFalse(create.add_required_skill(self.sid("SQL"), t))
        with self.assertRaises(ValueError):
            create.add_required_skill(9999, t)
        with self.assertRaises(ValueError):
            create.add_required_skill(self.sid("SQL"), 9999)

    def test_add_history(self):
        self.assertTrue(create.add_history("assigned", self.mid("Ben"), self.tid("Build REST API")))
        with self.assertRaises(ValueError):
            create.add_history("deleted", self.mid("Ben"), self.tid("Build REST API"))
        with self.assertRaises(ValueError):
            create.add_history("assigned", 9999, self.tid("Build REST API"))
        with self.assertRaises(ValueError):
            create.add_history("assigned", self.mid("Ben"), 9999)


# --------------------------------------------------------------------------- #
# 4. retrieve.py
# --------------------------------------------------------------------------- #
class TestRetrieve(BaseCase):
    def test_get_all_skills(self):
        rows = retrieve.get_all_skills()
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["name"] for r in rows], sorted(r["name"] for r in rows))

    def test_get_all_members_has_skills(self):
        rows = {r["name"]: r for r in retrieve.get_all_members()}
        self.assertEqual(len(rows), 7)
        self.assertEqual({s["name"] for s in rows["Aisha"]["skills"]}, {"Python", "SQL"})

    def test_get_all_tasks_shape(self):
        rows = {r["name"]: r for r in retrieve.get_all_tasks()}
        self.assertEqual(len(rows), 8)
        api = rows["Build REST API"]
        self.assertEqual(api["status"], "In Progress")
        self.assertEqual({a["name"] for a in api["assignments"]}, {"Aisha", "Gabe"})
        self.assertEqual([d["predecessor_name"] for d in api["dependencies"]], ["Design database schema"])
        self.assertEqual([s["name"] for s in api["required_skills"]], ["Python"])

    def test_get_all_history_order_and_count(self):
        rows = retrieve.get_all_history()
        self.assertEqual(len(rows), 8)
        ids = [r["change_id"] for r in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_get_all_dependencies_and_statuses(self):
        self.assertEqual(len(retrieve.get_all_dependencies()), 7)
        self.assertEqual([s["definition"] for s in retrieve.get_all_statuses()],
                         ["Pending", "In Progress", "Complete"])

    def test_get_task_history(self):
        rows = retrieve.get_task_history(self.tid("Implement login backend"))
        self.assertEqual([r["action"] for r in rows], ["assigned", "unassigned", "assigned"])
        self.assertEqual(retrieve.get_task_history(9999), [])


# --------------------------------------------------------------------------- #
# 5. update.py
# --------------------------------------------------------------------------- #
class TestUpdate(BaseCase):
    def test_update_member_role(self):
        member_id = self.mid("Ben")
        self.assertTrue(update.update_member_role(member_id, True))
        self.assertEqual(self.one("SELECT role FROM team_members WHERE member_id=?", (member_id,)), 1)
        with self.assertRaisesRegex(ValueError, "boolean"):
            update.update_member_role(member_id, 1)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            update.update_member_role(9999, False)

    def test_update_task_required_skills_replaces_set_atomically(self):
        task_id = create.add_task(1, "Requirement change test", 1, 2, self.status_id("Pending"))
        java_id = self.sid("Java")
        sql_id = self.sid("SQL")
        changed = update.update_task_required_skills(task_id, [java_id, sql_id, java_id])
        self.assertEqual(changed, {"added": sorted([java_id, sql_id]), "removed": []})
        rows = self.q("SELECT skill_id FROM required_skills WHERE task_id=? ORDER BY skill_id", (task_id,))
        self.assertEqual([row["skill_id"] for row in rows], sorted([java_id, sql_id]))
        changed = update.update_task_required_skills(task_id, [sql_id])
        self.assertEqual(changed, {"added": [], "removed": [java_id]})

    def test_update_task_required_skills_validates_task_and_skill_ids(self):
        with self.assertRaisesRegex(ValueError, "Task ID does not exist"):
            update.update_task_required_skills(9999, [])
        task_id = self.tid("Write API tests")
        with self.assertRaisesRegex(ValueError, "Skill ID does not exist"):
            update.update_task_required_skills(task_id, [9999])

    def test_simple_updates(self):
        m, s, t = self.mid("Ben"), self.sid("Java"), self.tid("Write API tests")
        self.assertTrue(update.update_member_name(m, "Benjamin"))
        self.assertTrue(update.update_member_availability(m, False))
        self.assertTrue(update.update_skill(s, "Java 21"))
        self.assertTrue(update.update_task_name(t, "API tests"))
        self.assertTrue(update.update_task_priority(t, 0))
        self.assertTrue(update.update_task_slack(t, 7))
        self.assertEqual(self.one("SELECT name FROM team_members WHERE member_id=?", (m,)), "Benjamin")
        self.assertEqual(self.one("SELECT available FROM team_members WHERE member_id=?", (m,)), 0)
        self.assertEqual(self.one("SELECT slack FROM tasks WHERE task_id=?", (t,)), 7)

    def test_update_validation(self):
        t = self.tid("Write API tests")
        with self.assertRaises(ValueError): update.update_member_name(9999, "x")
        with self.assertRaises(ValueError): update.update_member_name(self.mid("Ben"), " ")
        with self.assertRaises(ValueError): update.update_member_availability(self.mid("Ben"), 1)
        with self.assertRaises(ValueError): update.update_member_availability(9999, True)
        with self.assertRaises(ValueError): update.update_skill(self.sid("Java"), "Python")   # dup
        with self.assertRaises(ValueError): update.update_skill(9999, "x")
        with self.assertRaises(ValueError): update.update_task_name(9999, "x")
        with self.assertRaises(ValueError): update.update_task_priority(t, 6)
        with self.assertRaises(ValueError): update.update_task_slack(t, -1)
        with self.assertRaises(ValueError): update.update_task_duration(t, 0)
        with self.assertRaises(ValueError): update.update_task_duration(9999, 3)

    def test_update_status_rules(self):
        with self.assertRaises(ValueError):
            update.update_status(self.status_id("Complete"), "Done")      # protected
        with self.assertRaises(ValueError):
            update.update_status(9999, "x")
        with self.assertRaises(ValueError):
            update.update_status(self.status_id("Pending"), "Complete")   # dup
        self.assertTrue(update.update_status(self.status_id("In Progress"), "Doing"))

    def test_update_duration_recalculates_workload(self):
        t = self.tid("Implement login backend")        # Ben, 4 -> 10
        update.update_task_duration(t, 10)
        self.assertEqual(self.stored_workload(self.mid("Ben")), 10)
        self.assert_workloads_consistent()

    def test_update_status_recalculates_workload(self):
        t = self.tid("Implement login backend")
        update.update_task_status(t, self.status_id("Complete"))
        self.assertEqual(self.stored_workload(self.mid("Ben")), 0)
        update.update_task_status(t, self.status_id("In Progress"))
        self.assertEqual(self.stored_workload(self.mid("Ben")), 4)
        self.assert_workloads_consistent()

    def test_update_status_errors(self):
        t = self.tid("Write API tests")
        with self.assertRaises(ValueError): update.update_task_status(t, self.status_id("Pending"))  # unchanged
        with self.assertRaises(ValueError): update.update_task_status(t, 999)
        with self.assertRaises(ValueError): update.update_task_status(9999, 1)

    def test_reassign_task(self):
        t, old, new = self.tid("Implement login backend"), self.mid("Ben"), self.mid("Eli")
        b_old, e_old = self.stored_workload(old), self.stored_workload(new)
        out_id, in_id = update.reassign_task(t, old, new)
        self.assertEqual(self.one("SELECT action FROM history WHERE change_id=?", (out_id,)), "unassigned")
        self.assertEqual(self.one("SELECT action FROM history WHERE change_id=?", (in_id,)), "assigned")
        self.assertEqual(self.stored_workload(old), b_old - 4)
        self.assertEqual(self.stored_workload(new), e_old + 4)
        self.assert_workloads_consistent()

    def test_reassign_errors(self):
        t = self.tid("Implement login backend")
        ben, eli, aisha = self.mid("Ben"), self.mid("Eli"), self.mid("Aisha")
        with self.assertRaises(ValueError): update.reassign_task(t, ben, ben)
        with self.assertRaises(ValueError): update.reassign_task(t, eli, aisha)     # old not on task
        with self.assertRaises(ValueError): update.reassign_task(t, ben, 9999)
        with self.assertRaises(ValueError): update.reassign_task(9999, ben, eli)
        t2 = self.tid("Build REST API")
        with self.assertRaises(ValueError): update.reassign_task(t2, self.mid("Aisha"), self.mid("Gabe"))  # already on


# --------------------------------------------------------------------------- #
# 6. delete.py
# --------------------------------------------------------------------------- #
class TestDelete(BaseCase):
    def test_delete_member_rules(self):
        with self.assertRaises(ValueError): delete.delete_member(self.mid("Ben"))     # has tasks
        with self.assertRaises(ValueError): delete.delete_member(9999)
        m = create.add_member("Temp", 0, True)
        self.assertTrue(delete.delete_member(m))
        self.assertIsNone(self.one("SELECT 1 FROM team_members WHERE member_id=?", (m,)))

    def test_delete_member_keeps_history_with_null_assignee(self):
        m = create.add_member("Temp", 0, True)
        t = self.tid("Optimise queries")
        create.assign_task(t, m)
        delete.unassign_task(t, m)
        delete.delete_member(m)
        rows = retrieve.get_task_history(t)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["assignee_id"] is None for r in rows))

    def test_delete_skill(self):
        with self.assertRaises(ValueError): delete.delete_skill(self.sid("SQL"))      # required by tasks
        with self.assertRaises(ValueError): delete.delete_skill(9999)
        s = create.add_skill("Temp")
        self.assertTrue(delete.delete_skill(s))

    def test_delete_status(self):
        with self.assertRaises(ValueError): delete.delete_status(self.status_id("Pending"))
        with self.assertRaises(ValueError): delete.delete_status(self.status_id("Complete"))
        with self.assertRaises(ValueError): delete.delete_status(self.status_id("In Progress"))  # in use
        with self.assertRaises(ValueError): delete.delete_status(9999)
        s = create.add_status("Blocked")
        self.assertTrue(delete.delete_status(s))

    def test_delete_task_cascades_and_fixes_workload(self):
        t = self.tid("Implement login backend")
        delete.delete_task(t)
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=?", (t,)), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM required_skills WHERE task_id=?", (t,)), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM history WHERE task_id=?", (t,)), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM dependencies WHERE task_id=? OR predecessor_id=?", (t, t)), 0)
        self.assertEqual(self.stored_workload(self.mid("Ben")), 0)
        self.assert_workloads_consistent()
        with self.assertRaises(ValueError): delete.delete_task(t)

    def test_delete_member_skill_and_required_skill(self):
        self.assertTrue(delete.delete_member_skill(self.mid("Ben"), self.sid("Java")))
        self.assertFalse(delete.delete_member_skill(self.mid("Ben"), self.sid("Java")))
        self.assertTrue(delete.delete_required_skill(self.sid("SQL"), self.tid("Optimise queries")))
        self.assertFalse(delete.delete_required_skill(self.sid("SQL"), self.tid("Optimise queries")))

    def test_delete_dependency(self):
        dep = retrieve.get_all_dependencies()[0]["dependency_id"]
        self.assertTrue(delete.delete_dependency(dep))
        with self.assertRaises(ValueError): delete.delete_dependency(dep)

    def test_unassign_task(self):
        t, m = self.tid("Implement login backend"), self.mid("Ben")
        change_id = delete.unassign_task(t, m)
        self.assertEqual(self.one("SELECT action FROM history WHERE change_id=?", (change_id,)), "unassigned")
        self.assertEqual(self.stored_workload(m), 0)
        self.assert_workloads_consistent()
        with self.assertRaises(ValueError): delete.unassign_task(t, m)      # no longer assigned
        with self.assertRaises(ValueError): delete.unassign_task(9999, m)
        with self.assertRaises(ValueError): delete.unassign_task(t, 9999)


# --------------------------------------------------------------------------- #
# 7. End-to-end invariant: random-ish workflow keeps workloads consistent
# --------------------------------------------------------------------------- #
class TestWorkflow(BaseCase):
    def test_mixed_operations_keep_workloads_consistent(self):
        t_new = create.add_task(5, "Extra", 3, 0, self.status_id("Pending"))
        m_new = create.add_member("Newbie", 0, True)
        create.assign_task(t_new, m_new);                         self.assert_workloads_consistent()
        create.assign_task(t_new, self.mid("Ben"));               self.assert_workloads_consistent()
        update.update_task_duration(t_new, 9);                    self.assert_workloads_consistent()
        update.reassign_task(t_new, m_new, self.mid("Eli"));      self.assert_workloads_consistent()
        update.update_task_status(t_new, self.status_id("Complete")); self.assert_workloads_consistent()
        update.update_task_status(t_new, self.status_id("Pending"));  self.assert_workloads_consistent()
        delete.unassign_task(t_new, self.mid("Ben"));             self.assert_workloads_consistent()
        delete.delete_task(t_new);                                self.assert_workloads_consistent()


if __name__ == "__main__":
    unittest.main(verbosity=2)
