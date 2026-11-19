from tests.conftest import EngineTestCase
from db_operations import create, update
from engine import decisions, service
from engine.config import SETTINGS_KEY_THRESHOLDS
from engine import learning


class TestService(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.candidate = self.member("Candidate", ["Required"])
        self.lead = self.member("Lead", role=True)
        self.task_id = self.task(required_skills=["Required"])

    def test_recommend_approve_and_record_history(self):
        decision = service.recommend_task(self.task_id)
        self.assertEqual(decision["action"], "propose")
        result = service.approve_decision(decision["decision_id"], self.lead)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=? AND member_id=?",
                                  (self.task_id, self.candidate)), 1)
        self.assertEqual(self.one("SELECT COUNT(*) FROM history WHERE decision_id=?",
                                  (decision["decision_id"],)), 1)
        self.assertEqual(result["outcome"], "approved and applied")

    def test_structured_approval_reason_is_saved_and_learned(self):
        before = learning.get_weights()
        decision = service.recommend_task(self.task_id)
        result = service.approve_decision(decision["decision_id"], self.lead,
            reason_code="skill_match", rationale="Strong match to required skills")
        self.assertEqual(result["feedback_reason"]["code"], "skill_match")
        self.assertGreater(learning.get_weights()["fit"], before["fit"])

    def test_structured_rejection_reason_is_saved_and_learned(self):
        before = learning.get_weights()
        decision = service.recommend_task(self.task_id)
        result = service.reject_decision(decision["decision_id"], self.lead,
            reason_code="workload_concern", rationale="The proposed workload is too high")
        self.assertEqual(result["feedback_reason"]["code"], "workload_concern")
        self.assertGreater(learning.get_weights()["load"], before["load"])

    def test_recommendation_never_allocates_before_lead_approval(self):
        decision = service.recommend_task(self.task_id)
        self.assertEqual(decision["action"], "propose")
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=?", (self.task_id,)), 0)
        self.assertTrue(decision["candidate_comparison"])
        self.assertTrue(decision["evidence"])

    def test_waits_for_incomplete_predecessor(self):
        predecessor = self.task("Predecessor")
        child = self.task("Child", dependencies=[predecessor])
        decision = service.recommend_task(child)
        self.assertEqual(decision["action"], "wait")
        self.assertIn("predecessor", decision["reason"].lower())
        self.assertIn("revisit_when", decision)

    def test_staffed_task_can_be_reallocated_before_predecessor_finishes(self):
        incumbent = self.member("Incumbent")
        predecessor = self.task("Open predecessor")
        task_id = self.task("Dashboard UI", required_skills=["Required"],
                            assignees=[incumbent], dependencies=[predecessor])
        update.update_member_availability(incumbent, False)
        decision = service.recommend_task(task_id, leaving_member_id=incumbent)
        self.assertIn(decision["action"], ("propose", "ask"))
        self.assertNotEqual(decision["action"], "wait")

    def test_reject_and_reject_duplicate_protection(self):
        decision = service.recommend_task(self.task_id)
        rejected = service.reject_decision(decision["decision_id"], self.lead, note="Not now")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["outcome"], "rejected")
        self.assertEqual(rejected["lead_response"], "Not now")
        with self.assertRaisesRegex(ValueError, "Only pending"):
            service.reject_decision(decision["decision_id"], self.lead)

    def test_undo_approved_assignment(self):
        decision = service.recommend_task(self.task_id)
        approved = service.approve_decision(decision["decision_id"], self.lead)
        undone = service.undo_decision(decision["decision_id"], self.lead)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=?", (self.task_id,)), 0)

    def test_rejects_self_approval_and_non_approver(self):
        decision = service.recommend_task(self.task_id)
        with self.assertRaisesRegex(ValueError, "not allowed"):
            service.approve_decision(decision["decision_id"], self.candidate)
        involved_lead = self.member("Involved lead", role=True)
        involved_task = self.task("Assigned task", assignees=[involved_lead])
        proposal = decisions.create_decision({
            "task_id": involved_task, "leaving_member_id": involved_lead,
            "action": "propose", "confidence": 0.8, "reason": "Replace",
            "member_id": self.candidate,
            "plan": [{"op": "reassign", "task_id": involved_task,
                      "from": involved_lead, "to": self.candidate}],
        })
        with self.assertRaisesRegex(ValueError, "reallocation"):
            service.approve_decision(proposal, involved_lead)

    def test_clarification_records_learning_and_creates_proposal_without_allocating(self):
        alternate = self.member("Alternate", ["Required"], workload=1)
        # Force the close-score pathway so this scenario exercises ASK.
        learning._write_settings({SETTINGS_KEY_THRESHOLDS: {"propose": 0.9, "margin_full": 0.15}})
        ask = service.recommend_task(self.task_id)
        self.assertEqual(ask["action"], "ask")
        outcome = service.respond_to_clarification(
            ask["decision_id"], self.lead, preferred_member_id=alternate,
            response_text="Alternate has recent experience.")
        self.assertEqual(outcome["clarification"]["status"], "stale")
        self.assertEqual(outcome["clarification"]["clarification_response"]["text"],
                         "Alternate has recent experience.")
        proposal = outcome["reassessment"]
        self.assertEqual(proposal["action"], "propose")
        self.assertEqual(proposal["member_id"], alternate)
        self.assertEqual(proposal["clarification_response"]["preferred_member_id"], alternate)
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=?", (self.task_id,)), 0)
        self.assertEqual(decisions.get_decision(ask["decision_id"])["reassessment_decision_id"],
                         proposal["decision_id"])

    def test_clarification_reassessment_still_requires_separate_approval(self):
        self.member("Second candidate", ["Required"])
        learning._write_settings({SETTINGS_KEY_THRESHOLDS: {"propose": 0.9, "margin_full": 0.15}})
        ask = service.recommend_task(self.task_id)
        outcome = service.respond_to_clarification(ask["decision_id"], self.lead,
                                                   preferred_member_id=self.candidate,
                                                   response_text="Prior experience")
        proposal = outcome["reassessment"]
        with self.assertRaisesRegex(ValueError, "clarification request"):
            service.approve_decision(ask["decision_id"], self.lead, member_id=self.candidate)
        self.assertEqual(self.one("SELECT COUNT(*) FROM task_assignments WHERE task_id=?", (self.task_id,)), 0)
        approved = service.approve_decision(proposal["decision_id"], self.lead)
        self.assertEqual(approved["status"], "approved")




