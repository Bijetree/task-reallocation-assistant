from tests.conftest import EngineTestCase
from engine.models import Candidate, Factor
from engine.policy import confidence_of, decide, impact_blockers, is_low_impact


class TestPolicy(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.task_id = self.task()
        self.task_data = {
            "task_id": self.task_id, "name": "Task", "duration": 2,
            "priority": 1, "status": "Pending",
        }
        self.candidate = Candidate(1, "A", [Factor("fit", 1.0, 1.0, "strong fit")], 0.9)

    def test_impact_blocks_auto_for_progress_long_or_urgent_work(self):
        self.assertTrue(is_low_impact(self.task_data))
        self.assertIn("already", " ".join(impact_blockers({**self.task_data, "status": "In Progress"})))
        self.assertTrue(impact_blockers({**self.task_data, "duration": 5}))
        self.assertTrue(impact_blockers({**self.task_data, "priority": 5}))

    def test_confidence_accounts_for_margin(self):
        runner_up = Candidate(2, "B", [], 0.7)
        self.assertAlmostEqual(confidence_of([self.candidate, runner_up], 0.2), 0.9)
        self.assertEqual(confidence_of([], 0.2), 0.0)

    def test_no_candidate_returns_wait_with_revisit_reason(self):
        result = decide(self.task_data, None, [], {3: "No eligible member."})
        self.assertEqual(result["action"], "wait")
        self.assertIn("No eligible person", result["reason"])
        self.assertIn("revisit_when", result)

    def test_low_confidence_requests_human_choice(self):
        close = Candidate(2, "B", [], 0.89)
        result = decide(self.task_data, None, [self.candidate, close], {},
                        thresholds={"propose": 0.95, "margin_full": 0.15, "auto": 2.0})
        self.assertEqual(result["action"], "ask")
        self.assertEqual(len(result["options"]), 2)
        self.assertIn("question", result)

    def test_high_confidence_always_requires_explicit_approval(self):
        urgent = {**self.task_data, "priority": 5}
        result = decide(urgent, None, [self.candidate], {},
                        thresholds={"propose": 0.5, "margin_full": 0.15, "auto": 0.8})
        self.assertEqual(result["action"], "propose")
        self.assertTrue(result["approval_required"])
        self.assertNotIn("auto", result["action"])

