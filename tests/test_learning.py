from tests.conftest import EngineTestCase
from engine import decisions, learning, service
from engine.config import DEFAULT_WEIGHTS, SETTINGS_KEY_WEIGHTS


class TestLearning(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.member("A")
        self.b = self.member("B")
        self.approver = self.member("Lead", role=True)

    def test_default_weights_are_normalized(self):
        weights = learning.get_weights()
        self.assertEqual(set(weights), set(DEFAULT_WEIGHTS))
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_stored_weights_are_normalized_and_have_a_floor(self):
        learning._write_settings({SETTINGS_KEY_WEIGHTS: {"load": 1000, "fit": 0, "continuity": 0}})
        weights = learning.get_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertGreaterEqual(min(weights.values()), 0.02)

    def test_pairwise_feedback_moves_weights_toward_preferred_features(self):
        task_id = self.task()
        decision_id = decisions.create_decision({
            "task_id": task_id, "action": "propose", "confidence": 0.8,
            "reason": "Initial recommendation", "member_id": self.a,
            "plan": [{"op": "assign", "task_id": task_id, "member_id": self.a}],
            "factors": {
                str(self.a): {"load": 0.1, "fit": 0.2, "continuity": 0.0},
                str(self.b): {"load": 0.9, "fit": 0.2, "continuity": 0.0},
            },
        })
        before = learning.get_weights()
        self.assertTrue(learning.learn_from_decision(decision_id, preferred_member_id=self.b))
        after = learning.get_weights()
        self.assertGreater(after["load"], before["load"])
        self.assertLess(after["fit"], before["fit"])
        self.assertAlmostEqual(sum(after.values()), 1.0)

    def test_rejecting_proposal_updates_candidate_weights(self):
        task_id = self.task()
        decision_id = decisions.create_decision({
            "task_id": task_id, "action": "propose", "confidence": 0.8,
            "reason": "Initial recommendation", "member_id": self.a,
            "plan": [{"op": "assign", "task_id": task_id, "member_id": self.a}],
            "factors": {
                str(self.a): {"load": 0.1, "fit": 0.2, "continuity": 0.0},
                str(self.b): {"load": 0.9, "fit": 0.2, "continuity": 0.0},
            },
        })
        before = learning.get_weights()["load"]
        service.reject_decision(decision_id, self.approver)
        self.assertGreater(learning.get_weights()["load"], before)

    def test_feedback_adjusts_proposal_threshold_after_minimum_events(self):
        for index in range(10):
            task_id = self.task(name=f"Task {index}")
            decision_id = decisions.create_decision({
                "task_id": task_id, "action": "propose", "confidence": 0.8,
                "reason": "Proposal", "member_id": self.a,
                "plan": [{"op": "assign", "task_id": task_id, "member_id": self.a}],
            })
            decisions.set_status(decision_id, "rejected", approver_id=self.approver)
        thresholds = learning.refresh_thresholds()
        self.assertGreater(thresholds["propose"], 0.55)

    def test_automatic_threshold_stays_disabled_without_history(self):
        self.assertGreater(learning.get_thresholds()["auto"], 1.0)



