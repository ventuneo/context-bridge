"""First measurable retention tests on the synthetic reference cases in quality/cases/."""

from __future__ import annotations

import importlib.util
import sys
import unittest

import helpers
from helpers import REPO_ROOT

_spec = importlib.util.spec_from_file_location("cb_quality_evaluate", REPO_ROOT / "quality" / "evaluate.py")
assert _spec and _spec.loader
evaluate = importlib.util.module_from_spec(_spec)
sys.modules["cb_quality_evaluate"] = evaluate
_spec.loader.exec_module(evaluate)

CASE = evaluate.CASES / "basic"


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = helpers.TempProject()  # provides an isolated fake home
        self.addCleanup(self.project.cleanup)
        self.enterContext(helpers.patched_home(self.project.home))

    def test_default_budget_keeps_everything_important(self) -> None:
        m = evaluate.run_case(CASE, budget=2000)
        self.assertEqual(m["critical_recall"], 1.0, m["missing"])
        self.assertGreaterEqual(m["score"], 90, m)
        self.assertEqual(m["status_accuracy"], 1.0)
        self.assertEqual(m["forbidden_hits"], [])

    def test_tight_budget_drops_context_before_critical_items(self) -> None:
        m = evaluate.run_case(CASE, budget=600)
        self.assertEqual(m["critical_recall"], 1.0, m["missing"])
        self.assertEqual(m["forbidden_hits"], [])
        self.assertLessEqual(m["tokens"], 600)
        self.assertTrue(all(not i.startswith(("G", "C", "D", "N")) for i in m["missing"]), m["missing"])

    def test_score_never_rises_when_the_budget_shrinks(self) -> None:
        scores = [evaluate.run_case(CASE, budget=b)["score"] for b in (600, 1000, 2000)]
        self.assertEqual(scores, sorted(scores))

    def test_critical_loss_under_a_hard_budget_is_always_reported(self) -> None:
        m = evaluate.run_case(CASE, budget=350, hard_budget=True)
        self.assertLess(m["critical_recall"], 1.0)  # the scenario really loses critical items ...
        self.assertTrue(m["critical_loss_reported"])  # ... and the pack says so
        self.assertEqual(m["exit_code"], 3)
        self.assertLessEqual(m["tokens"], 350)
        self.assertEqual(m["forbidden_hits"], [])


if __name__ == "__main__":
    unittest.main()
