"""Context Quality Score: gates, baseline and the five measured properties (synthetic cases only)."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

import helpers
import packtools
from helpers import REPO_ROOT

from context_bridge import pack

if "cb_quality_evaluate" in sys.modules:
    evaluate = sys.modules["cb_quality_evaluate"]
else:
    _spec = importlib.util.spec_from_file_location("cb_quality_evaluate", REPO_ROOT / "quality" / "evaluate.py")
    assert _spec and _spec.loader
    evaluate = importlib.util.module_from_spec(_spec)
    sys.modules["cb_quality_evaluate"] = evaluate
    _spec.loader.exec_module(evaluate)

_RESULTS: list[dict] | None = None


def results() -> list[dict]:
    """The full matrix (all cases × budgets × modes), computed once per test run."""
    global _RESULTS
    if _RESULTS is None:
        project = helpers.TempProject()
        try:
            with helpers.patched_home(project.home):
                _RESULTS = evaluate.run_matrix()
        finally:
            project.cleanup()
    return _RESULTS


def runs(case: str | None = None, mode: str | None = None, budget: int | None = None) -> list[dict]:
    return [r for r in results() if (case in (None, r["case"])) and (mode in (None, r["mode"]))
            and (budget in (None, r["budget"]))]  # fmt: skip


def reference(case: str) -> dict:
    gates = evaluate.gates(evaluate.load_case(evaluate.CASES / case)[0])
    return runs(case, "soft", gates["reference_budget"])[0]


CASE_NAMES = [p.name for p in evaluate.list_cases()]


class GateTests(unittest.TestCase):
    def test_there_are_several_cases_including_a_large_one(self) -> None:
        self.assertGreaterEqual(len(CASE_NAMES), 5)
        self.assertGreater(
            reference("large")["source_tokens"],
            20 * max(reference(c)["source_tokens"] for c in CASE_NAMES if c != "large"),
        )

    def test_all_gates_pass(self) -> None:
        self.assertEqual(evaluate.check_gates(results()), [])

    def test_no_regression_against_the_baseline(self) -> None:
        baseline = evaluate.load_baseline()
        self.assertEqual({r["case"] for r in results()}, set(baseline))
        self.assertEqual(evaluate.compare_baseline(results(), baseline), [])


class MeasuredPropertyTests(unittest.TestCase):
    def test_1_facts_and_decisions_are_complete_at_the_reference_budget(self) -> None:
        for case in CASE_NAMES:
            ref = reference(case)
            for category in ("decision", "fact"):
                found, total = ref["by_category"].get(category, [0, 0])
                with self.subTest(case=case, category=category):
                    self.assertEqual(found, total, ref["missing"])

    def test_2_goals_constraints_and_next_steps_survive_every_soft_budget(self) -> None:
        for r in runs(mode="soft"):
            with self.subTest(case=r["case"], budget=r["budget"]):
                self.assertEqual(r["critical_missing"], [])
                for category in ("goal", "constraint", "next_step"):
                    critical = [v for v in r["items"] if v["category"] == category and v["criticality"] == "critical"]
                    self.assertTrue(all(v["found"] for v in critical), category)

    def test_3_loss_across_budgets_is_measured_and_always_reported(self) -> None:
        for case in CASE_NAMES:
            hard = sorted(runs(case, "hard"), key=lambda r: r["budget"])
            self.assertEqual([r["score"] for r in hard], sorted(r["score"] for r in hard))
            for r in hard:
                self.assertLessEqual(r["tokens"], r["budget"])  # a hard budget is never exceeded
                if r["critical_missing"]:
                    self.assertTrue(r["loss_reported"] and r["pack_exit"] == 3 and r["verify_exit"] == 3)
        large = {r["budget"]: r for r in runs("large", "hard")}
        self.assertGreater(len(large[500]["critical_missing"]), 0)  # the scenario really loses information
        self.assertLess(large[500]["score"], large[1000]["score"])
        self.assertLess(large[1000]["score"], large[4000]["score"])

    def test_4_compression_efficiency_small_and_large(self) -> None:
        large = reference("large")
        self.assertLessEqual(large["compression"], 0.2)
        for r in runs("large"):
            self.assertLess(r["compression"], 0.25)
        small = [reference(c) for c in CASE_NAMES if c != "large"]
        # Honest finding: for tiny projects the pack is larger than its sources (fixed overhead).
        self.assertTrue(all(r["compression"] > 1 for r in small))
        self.assertTrue(all(r["tokens"] <= 1200 for r in small))

    def test_5_facts_assumptions_and_unverifiable_session_notes_are_told_apart(self) -> None:
        for r in results():
            with self.subTest(case=r["case"], budget=r["budget"], mode=r["mode"]):
                self.assertIn(r["status_accuracy"], (None, 1.0), r["mismatches"])
                self.assertIn(r["provenance_accuracy"], (None, 1.0), r["mismatches"])
        for case in CASE_NAMES:
            with self.subTest(case=case):
                self.assertIn(reference(case)["flags_accuracy"], (None, 1.0), reference(case)["mismatches"])

    def test_5b_session_items_are_marked_unverified_in_markdown(self) -> None:
        project = helpers.TempProject()
        self.addCleanup(project.cleanup)
        with helpers.patched_home(project.home), mock.patch.dict(os.environ, packtools.GIT_ENV):
            expected, handoff = evaluate.load_case(evaluate.CASES / "conflicts")
            root = evaluate.prepare(evaluate.CASES / "conflicts", project.base, expected)
            result = pack.build(root, handoff=handoff, approve=True, dry_run=True)
        origins = {s["id"]: s["origin"] for s in result.pack["sources"]}
        item_lines = [line for line in result.markdown.splitlines() if line.startswith("- [")]
        self.assertEqual(len(item_lines), sum(len(s["items"]) for s in result.pack["sections"]))
        self.assertIn("session", origins.values())
        for line in item_lines:
            source_id = re.search(r" — (S\d+) ", line).group(1)
            with self.subTest(line=line[:60]):
                self.assertEqual("(unverified)" in line, origins[source_id] == "session")

    def test_6_forbidden_content_never_appears(self) -> None:
        self.assertEqual(
            [(r["case"], r["budget"], r["mode"], r["forbidden_hits"]) for r in results() if r["forbidden_hits"]], []
        )


class EvaluatorTests(unittest.TestCase):
    """The score is counted from ground truth; these tests pin the arithmetic."""

    @staticmethod
    def fake_pack(items: list[dict], session_ids: tuple[str, ...] = ()) -> dict:
        sources = [{"id": f"S{i}", "origin": "session" if f"S{i}" in session_ids else "file", "label": f"f{i}.md"}
                   for i in range(1, 4)]  # fmt: skip
        return {"sources": sources, "sections": [{"items": items}], "budget": {"estimated_tokens": 200},
                "critical_loss": []}  # fmt: skip

    def test_score_is_points_found_over_points_possible(self) -> None:
        expected = {"items": [
            {"id": "A", "category": "goal", "criticality": "critical", "all": ["alpha"]},
            {"id": "B", "category": "fact", "criticality": "important", "all": ["beta"]},
            {"id": "C", "category": "fact", "criticality": "normal", "all": ["gamma"]},
        ], "forbidden": []}  # fmt: skip
        item = {"id": "I1", "text": "Alpha goal", "status": "fact", "source": "S1", "flags": []}
        m = evaluate.evaluate(self.fake_pack([item]), "", expected)
        self.assertEqual((m["points"], m["max_points"], m["score"]), (3, 6, 50.0))
        self.assertEqual((m["critical_found"], m["critical_total"], m["missing"]), (1, 1, ["B", "C"]))
        self.assertEqual(m["points_per_1k_tokens"], 15.0)

    def test_wrong_status_origin_and_flags_are_detected(self) -> None:
        expected = {"items": [{"id": "A", "category": "assumption", "criticality": "important", "all": ["tablet"],
                               "status": "assumption", "origin": "file", "flags": ["unlabeled"]}], "forbidden": []}  # fmt: skip
        item = {"id": "I1", "text": "Every farm has a tablet", "status": "fact", "source": "S2", "flags": []}
        m = evaluate.evaluate(self.fake_pack([item], session_ids=("S2",)), "", expected)
        self.assertEqual((m["status_accuracy"], m["provenance_accuracy"], m["flags_accuracy"]), (0.0, 0.0, 0.0))
        self.assertEqual(set(m["mismatches"]), {"status", "provenance", "flags"})

    def test_forbidden_content_is_found_in_json_and_markdown(self) -> None:
        expected = {"items": [], "forbidden": [{"id": "F1", "any": ["top secret value"]}]}
        self.assertEqual(
            evaluate.evaluate(self.fake_pack([]), "a TOP  secret value", expected)["forbidden_hits"], ["F1"]
        )

    def test_gates_name_every_failure(self) -> None:
        base = dict(reference("basic"))
        soft_loss = {**base, "critical_missing": ["G1"]}
        hidden_loss = {**base, "mode": "hard", "critical_missing": ["G1"], "loss_reported": False}
        failures = evaluate.check_gates([soft_loss, hidden_loss])
        self.assertTrue(any("CRITICAL LOSS without --hard-budget" in f for f in failures))
        self.assertTrue(any("was not reported clearly" in f for f in failures))
        regression = {**base, "score": base["score"] - 6}
        self.assertTrue(evaluate.compare_baseline([regression], evaluate.load_baseline()))


if __name__ == "__main__":
    unittest.main()
