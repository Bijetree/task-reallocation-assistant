from tests.conftest import EngineTestCase
from db_operations import create, update
from engine import decisions, service, triggers


class TestTriggers(EngineTestCase):
    def test_unavailable_member_gets_replacement_recommendation(self):
        incumbent = self.member("Unavailable", ["Python"])
        replacement = self.member("Replacement", ["Python"])
        task_id = self.task(required_skills=["Python"], assignees=[incumbent])
        update.update_member_availability(incumbent, False)
        results = triggers.member_became_unavailable(incumbent)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_id"], task_id)
        self.assertEqual(results[0]["member_id"], replacement)

    def test_returning_member_wakes_wait_decision(self):
        incumbent = self.member("Incumbent")
        returning = self.member("Returning", available=False)
        task_id = self.task(assignees=[incumbent])
        wait_id = decisions.create_decision({
            "task_id": task_id, "leaving_member_id": incumbent, "action": "wait",
            "confidence": 1.0, "reason": "No available replacement",
            "revisit_when": "Returning member becomes available",
        })
        update.update_member_availability(returning, True)
        results = triggers.member_became_available(returning)
        self.assertEqual(len(results), 1)
        self.assertEqual(decisions.get_decision(wait_id)["status"], "stale")
        self.assertEqual(results[0]["action"], "propose")

    def test_gained_skill_reconsiders_waiting_unassigned_task(self):
        candidate = self.member("Candidate")
        skill_id = self.skill("Testing")
        task_id = self.task("Needs testing", required_skills=["Testing"])
        waiting = service.recommend_task(task_id)
        self.assertEqual(waiting["action"], "wait")
        create.add_member_skill(candidate, skill_id)
        results = triggers.member_skill_added(candidate, skill_id)
        self.assertEqual(len(results), 1)
        self.assertIn(results[0]["action"], ("propose", "ask"))
        self.assertEqual(decisions.get_decision(waiting["decision_id"])["status"], "stale")

    def test_task_creation_trigger_only_allocates_unassigned_active_task(self):
        candidate = self.member("Candidate")
        task_id = self.task()
        result = triggers.task_created(task_id)
        self.assertEqual(result["action"], "propose")
        self.assertEqual(result["member_id"], candidate)
        self.assertEqual(triggers.task_became_unassigned(task_id)["decision_id"], result["decision_id"])

    def test_dependency_completion_reconsiders_waiting_task(self):
        self.member("Candidate")
        predecessor = self.task("Predecessor")
        child = self.task("Child", dependencies=[predecessor])
        waiting = service.recommend_task(child)
        self.assertEqual(waiting["action"], "wait")
        update.update_task_status(predecessor, self._statuses["Complete"])
        results = triggers.predecessor_completed(predecessor)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "propose")
        self.assertEqual(decisions.get_decision(waiting["decision_id"])["status"], "stale")

    def test_scheduled_sweep_surfaces_slack_risk_and_allocates_unassigned(self):
        self.member("Candidate")
        risk_task = self.task("At risk", slack=0)
        result = triggers.run_scheduled_sweep()
        self.assertIn(risk_task, result["at_risk_task_ids"])
        self.assertTrue(any(d["task_id"] == risk_task for d in result["decisions"]))
        self.assertEqual(result["expired"], 0)

    def test_overload_ratio_validation(self):
        member_id = self.member("Member")
        with self.assertRaises(ValueError):
            triggers.member_became_overloaded(member_id, ratio=1)

    def test_changed_required_skills_reassesses_waiting_task(self):
        candidate = self.member("Candidate", ["New skill"])
        task_id = self.task("Changing skills", required_skills=["Old skill"])
        waiting = service.recommend_task(task_id)
        self.assertEqual(waiting["action"], "wait")
        new_skill_id = self.skill("New skill")
        update.update_task_required_skills(task_id, [new_skill_id])
        result = triggers.task_required_skills_changed(task_id)
        self.assertEqual(result["action"], "propose")
        self.assertEqual(result["member_id"], candidate)
        self.assertEqual(decisions.get_decision(waiting["decision_id"])["status"], "stale")

    def test_new_required_skill_on_staffed_task_proposes_additional_coverage(self):
        incumbent = self.member("Incumbent")
        extra = self.member("Skill holder", ["New skill"])
        task_id = self.task("Skill gap", assignees=[incumbent])
        new_skill = self.skill("New skill")
        update.update_task_required_skills(task_id, [new_skill])
        result = triggers.task_required_skills_changed(task_id)
        self.assertEqual(result["action"], "propose")
        self.assertEqual(result["member_id"], extra)



