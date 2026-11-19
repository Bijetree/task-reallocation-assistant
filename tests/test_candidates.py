from tests.conftest import EngineTestCase
from engine.candidates import eligible_candidates
from engine.context import load_context


class TestCandidates(EngineTestCase):
    def test_filters_unavailable_and_already_assigned_members(self):
        required = self.skill("Python")
        incumbent = self.member("Incumbent", ["Python"])
        available = self.member("Available", ["Python"])
        unavailable = self.member("Unavailable", ["Python"], available=False)
        task_id = self.task(required_skills=["Python"], assignees=[incumbent])
        eligible, rejected, gap = eligible_candidates(load_context(), task_id, incumbent)
        self.assertEqual([m["member_id"] for m in eligible], [available])
        self.assertIn(unavailable, rejected)
        self.assertEqual(gap, {required})

    def test_remaining_assignee_can_cover_skill_gap(self):
        python = self.member("Python", ["Python"])
        frontend = self.member("Frontend", ["Frontend"])
        replacement = self.member("Replacement", ["Frontend"])
        task_id = self.task(required_skills=["Python", "Frontend"], assignees=[python, frontend])
        eligible, _rejected, gap = eligible_candidates(load_context(), task_id, frontend)
        self.assertEqual(gap, {self.skill("Frontend")})
        self.assertIn(replacement, {m["member_id"] for m in eligible})

    def test_candidate_must_cover_uncovered_required_skills(self):
        incumbent = self.member("Incumbent")
        partial = self.member("Partial", ["SQL"])
        qualified = self.member("Qualified", ["SQL", "Testing"])
        task_id = self.task(required_skills=["SQL", "Testing"], assignees=[incumbent])
        eligible, rejected, gap = eligible_candidates(load_context(), task_id, incumbent)
        self.assertEqual(gap, {self.skill("SQL"), self.skill("Testing")})
        self.assertEqual([m["member_id"] for m in eligible], [qualified])
        self.assertIn(partial, rejected)



