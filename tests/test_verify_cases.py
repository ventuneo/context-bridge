"""Regression: verify must accept genuine packs of every reference case (no false alarms)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import REPO_ROOT

from context_bridge import pack, verify

if "cb_quality_evaluate" in sys.modules:
    evaluate = sys.modules["cb_quality_evaluate"]
else:
    _spec = importlib.util.spec_from_file_location("cb_quality_evaluate", REPO_ROOT / "quality" / "evaluate.py")
    assert _spec and _spec.loader
    evaluate = importlib.util.module_from_spec(_spec)
    sys.modules["cb_quality_evaluate"] = evaluate
    _spec.loader.exec_module(evaluate)


class GenuinePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = helpers.TempProject()
        self.addCleanup(self.project.cleanup)
        self.enterContext(helpers.patched_home(self.project.home))

    def test_every_case_verifies_without_errors(self) -> None:
        cases = sorted(p for p in evaluate.CASES.iterdir() if (p / "expected.json").is_file())
        self.assertTrue(cases)
        for case_dir in cases:
            expected, handoff = evaluate.load_case(case_dir)
            for budget, hard in ((2000, False), (600, False), (350, True)):
                with self.subTest(case=case_dir.name, budget=budget, hard=hard), tempfile.TemporaryDirectory() as tmp:
                    root = evaluate.prepare(case_dir, Path(tmp), expected)
                    result = pack.build(root, handoff=handoff, approve=True, budget=budget, hard_budget=hard)
                    report = verify.verify(root)
                    self.assertEqual(report.errors, [])
                    # verify reports critical loss with 3 and partial coverage with 1, never "ok" for an incomplete pack
                    coverage = result.pack["coverage"]["status"]
                    wanted_exit = 3 if result.pack["critical_loss"] else 1 if coverage == "partial" else 0
                    self.assertEqual(report.exit_code, wanted_exit, report.findings)
                    self.assertEqual(coverage == "critical_loss", bool(result.pack["critical_loss"]))
                    self.assertTrue(all(s.status in ("fresh", "not_checkable") for s in report.sources))


if __name__ == "__main__":
    unittest.main()
