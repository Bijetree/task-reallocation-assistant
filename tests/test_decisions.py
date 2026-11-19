import json

from tests.conftest import EngineTestCase
from engine import decisions


class TestDecisions(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.member_id = self.member("Candidate")
        self.task_id = self.task()

    def proposal(self, **overrides):
        decision = {
            "task_id": self.task_id,
            "action": "propose",
            "confidence": 0.8,
            "reason": "Best fit",
            "member_id": self.member_id,
            "plan": [{"op": "assign", "task_id": self.task_id, "member_id": self.member_id}],
            "factors": {str(self.member_id): {"load": 0.8, "fit": 1.0, "continuity": 0.0}},
            "alternatives": [],
        }
        decision.update(overrides)
        return decision

    def test_schema_check_and_saved_decision_round_trip(self):
        self.assertTrue(decisions.check_schema())
        decision_id = decisions.create_decision(self.proposal())
        decision = decisions.get_decision(decision_id)
        self.assertEqual(decision["action"], "propose")
        self.assertEqual(decision["factors"][self.member_id]["fit"], 1.0)
        self.assertEqual(decision["plan"][0]["op"], "assign")

    def test_duplicate_open_decision_is_rejected(self):
        decisions.create_decision(self.proposal())
        with self.assertRaisesRegex(ValueError, "open decision"):
            decisions.create_decision(self.proposal())

    def test_status_transitions_and_pending_filter(self):
        decision_id = decisions.create_decision(self.proposal())
        self.assertEqual(len(decisions.list_pending()), 1)
        decisions.set_status(decision_id, "rejected", note="Try another option")
        self.assertEqual(decisions.get_decision(decision_id)["note"], "Try another option")
        self.assertEqual(decisions.list_pending(), [])
        with self.assertRaisesRegex(ValueError, "Cannot go"):
            decisions.set_status(decision_id, "approved")

    def test_ask_details_and_expiry(self):
        decision_id = decisions.create_decision({
            "task_id": self.task_id, "action": "ask", "confidence": 0.2,
            "reason": "Candidates are close", "question": "Who should take it?",
            "options": [{"member_id": self.member_id, "name": "Candidate"}],
        })
        self.assertEqual(decisions.get_decision(decision_id)["question"], "Who should take it?")
        self.assertEqual(decisions.expire_older_than(hours=0), 1)
        self.assertEqual(decisions.get_decision(decision_id)["status"], "expired")

    def test_feedback_counts(self):
        decision_id = decisions.create_decision(self.proposal())
        decisions.set_status(decision_id, "approved")
        self.assertEqual(decisions.feedback_stats()["accepted"], 1)

