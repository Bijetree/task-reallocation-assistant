import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db
from db_operations import create, update


class EngineTestCase(unittest.TestCase):
    """Each engine test gets an isolated, empty SQLite database."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = (db.DB_DIR, db.DB_PATH)
        db.DB_DIR = Path(self._tmp.name)
        db.DB_PATH = db.DB_DIR / "engine-test.db"
        db.initialise_database()
        self._skills = {}
        self._statuses = {
            row["definition"]: row["status_id"]
            for row in self.rows("SELECT status_id, definition FROM status")
        }

    def tearDown(self):
        db.DB_DIR, db.DB_PATH = self._old_db
        self._tmp.cleanup()

    def rows(self, sql, params=()):
        conn = db.get_connection()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0][0] if rows else None

    def skill(self, name):
        if name not in self._skills:
            self._skills[name] = create.add_skill(name)
        return self._skills[name]

    def member(self, name, skills=(), available=True, role=False, workload=0):
        member_id = create.add_member(name, workload, available, role)
        for skill_name in skills:
            create.add_member_skill(member_id, self.skill(skill_name))
        return member_id

    def task(self, name="Task", duration=2, priority=1, slack=5,
             status="Pending", required_skills=(), assignees=(), dependencies=()):
        task_id = create.add_task(duration, name, priority, slack, self._statuses[status])
        for skill_name in required_skills:
            create.add_required_skill(self.skill(skill_name), task_id)
        for member_id in assignees:
            update.assign_member(task_id, member_id)
        for predecessor_id in dependencies:
            create.add_dependency(predecessor_id, task_id)
        return task_id

    def assign(self, task_id, member_id):
        return update.assign_member(task_id, member_id)

    def set_status(self, task_id, status):
        return update.update_task_status(task_id, self._statuses[status])
