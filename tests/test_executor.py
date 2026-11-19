from tests.conftest import EngineTestCase
from db_operations import update
from engine import context, executor


class TestExecutor(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.old = self.member("Old")
        self.new = self.member("New")
        self.task_id = self.task(assignees=[self.old])

    def test_make_plan_for_initial_assignment_and_reassignment(self):
        self.assertEqual(executor.make_plan(self.task_id, None, self.new), [
            {"op": "assign", "task_id": self.task_id, "member_id": self.new}
        ])
        self.assertEqual(executor.make_plan(self.task_id, self.old, self.new), [
            {"op": "reassign", "task_id": self.task_id, "from": self.old, "to": self.new}
        ])

    def test_invert_reverses_and_reverses_order(self):
        plan = [
            {"op": "assign", "task_id": self.task_id, "member_id": self.new},
            {"op": "unassign", "task_id": self.task_id, "member_id": self.old},
        ]
        self.assertEqual(executor.invert(plan), [
            {"op": "assign", "task_id": self.task_id, "member_id": self.old},
            {"op": "unassign", "task_id": self.task_id, "member_id": self.new},
        ])

    def test_execute_and_undo_reassignment(self):
        plan = executor.make_plan(self.task_id, self.old, self.new)
        executor.execute(plan, decision_id=None)
        task = context.load_context()["tasks"][self.task_id]
        self.assertEqual({a["member_id"] for a in task["assignees"]}, {self.new})
        executor.execute(executor.invert(plan))
        task = context.load_context()["tasks"][self.task_id]
        self.assertEqual({a["member_id"] for a in task["assignees"]}, {self.old})

    def test_can_apply_checks_current_assignments_and_task_status(self):
        ctx = context.load_context()
        self.assertTrue(executor.can_apply(executor.make_plan(self.task_id, self.old, self.new), ctx))
        update.update_task_status(self.task_id, self._statuses["Complete"])
        self.assertFalse(executor.can_apply(executor.make_plan(self.task_id, self.old, self.new), context.load_context()))

    def test_failed_multi_step_execution_rolls_back_prior_steps(self):
        invalid_plan = [
            {"op": "assign", "task_id": self.task_id, "member_id": self.new},
            {"op": "not-an-operation", "task_id": self.task_id},
        ]
        with self.assertRaisesRegex(ValueError, "Unknown operation"):
            executor.execute(invalid_plan)
        assigned = {a["member_id"] for a in context.load_context()["tasks"][self.task_id]["assignees"]}
        self.assertEqual(assigned, {self.old})

