from tests.conftest import EngineTestCase
from engine.context import load_context
from engine.scoring import explain, explain_margin, rank_candidates, score_candidates


class TestScoring(EngineTestCase):
    def test_score_combines_load_fit_and_predecessor_continuity(self):
        sql = self.member("SQL owner", ["SQL"])
        other = self.member("Other", ["Python"])
        predecessor = self.task("Predecessor", status="Complete", assignees=[sql])
        task_id = self.task(required_skills=["SQL"], dependencies=[predecessor])
        ctx = load_context()
        sql_candidate = score_candidates(ctx, task_id, ctx["members"][sql])
        other_candidate = score_candidates(ctx, task_id, ctx["members"][other])
        self.assertEqual(sql_candidate.factor_values(), {"load": 0.9, "fit": 1.0, "continuity": 1.0})
        self.assertGreater(sql_candidate.score, other_candidate.score)

    def test_rank_is_descending_with_member_id_tie_break(self):
        first = self.member("First")
        second = self.member("Second")
        task_id = self.task()
        ctx = load_context()
        ranked = rank_candidates(ctx, task_id, [ctx["members"][second], ctx["members"][first]])
        self.assertEqual([c.member_id for c in ranked], [first, second])

    def test_explanations_include_factor_reason_and_margin(self):
        first = self.member("Preferred", ["SQL"])
        second = self.member("Alternative")
        task_id = self.task(required_skills=["SQL"])
        ctx = load_context()
        ranked = rank_candidates(ctx, task_id, [ctx["members"][first], ctx["members"][second]])
        self.assertIn("Preferred", explain(ranked[0]))
        self.assertNotIn(";", explain(ranked[0]))
        self.assertIn("\n- ", explain(ranked[0]))
        self.assertIn("ahead of Alternative", explain_margin(ranked[0], ranked[1]))

