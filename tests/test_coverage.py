"""Requirement: a pack must never be presented as complete or lossless when information is missing."""

from __future__ import annotations

import json
import os
import re
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

import helpers
import packtools
from helpers import TempProject
from packtools import tamper

from context_bridge import pack, resume, verify

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CLAIMS = re.compile(r"\b(lossless|loss-free|verlustfrei|vollständig|fully complete|complete pack|nothing (?:was )?lost)\b",
                    re.IGNORECASE)  # fmt: skip


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.enterContext(helpers.patched_home(self.project.home))
        self.enterContext(mock.patch.dict(os.environ, packtools.GIT_ENV))
        packtools.make_project(self.project)
        self.root = self.project.root

    def build(self, **kwargs: object) -> pack.PackResult:
        return pack.build(self.root, approve=True, now=NOW, **kwargs)  # type: ignore[arg-type]

    def many(self, key: str, n: int) -> bytes:
        return json.dumps({key: [{"text": f"Item {k}: keep requirement number {k} intact.", "status": "fact"}
                                 for k in range(n)]}).encode()  # fmt: skip

    def test_all_kept_is_stated_without_claiming_completeness(self) -> None:
        result = self.build()
        coverage = result.pack["coverage"]
        self.assertEqual(coverage["status"], "all_extracted_items_kept")
        self.assertEqual(coverage["extraction"], "selective")
        self.assertIn("not a full copy of the project", coverage["statement"])
        self.assertIn("> **Coverage:** All", result.markdown.split("## ")[0])

    def test_partial_coverage_is_a_warning_and_visible_at_the_top(self) -> None:
        result = self.build(budget=400, handoff=self.many("open_questions", 15))
        coverage = result.pack["coverage"]
        self.assertEqual(coverage["status"], "partial")
        self.assertGreater(coverage["dropped_items"]["important"] + coverage["dropped_items"]["context"], 0)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("**Coverage:** PARTIAL", result.markdown.split("## ")[0])
        report = verify.verify(self.root, now=NOW + timedelta(hours=1))
        self.assertIn("partial_coverage", {f.code for f in report.findings if f.severity == "warning"})
        self.assertNotEqual(report.result, "ok")
        _report, output = resume.resume(self.root, now=NOW + timedelta(hours=1))
        self.assertIn("Coverage: PARTIAL", output.split("<context_bridge_pack")[0])

    def test_critical_loss_is_the_coverage_status(self) -> None:
        result = self.build(budget=300, hard_budget=True, handoff=self.many("goals", 40))
        self.assertEqual(result.pack["coverage"]["status"], "critical_loss")
        self.assertTrue(result.pack["coverage"]["statement"].startswith("CRITICAL INFORMATION LOSS"))
        _report, output = resume.resume(self.root, now=NOW + timedelta(hours=1))
        header = output.split("<context_bridge_pack")[0]
        self.assertIn("CRITICAL INFORMATION LOSS", header)

    def test_a_pack_that_overstates_its_coverage_is_rejected(self) -> None:
        self.build(budget=400, handoff=self.many("open_questions", 15))

        def overstate(p: dict) -> None:
            p["coverage"] = {**p["coverage"], "status": "all_extracted_items_kept",
                             "dropped_items": {"critical": 0, "important": 0, "context": 0}}  # fmt: skip
            p["warnings"] = [w for w in p["warnings"] if w["code"] != "partial_coverage"]

        tamper(self.root, overstate)
        report = verify.verify(self.root, now=NOW + timedelta(hours=1))
        self.assertIn("coverage_misstated", {f.code for f in report.errors})
        self.assertIsNone(resume.resume(self.root, now=NOW + timedelta(hours=1))[1])

    def test_no_output_ever_claims_completeness(self) -> None:
        for kwargs in ({}, {"budget": 400, "handoff": self.many("open_questions", 15)},
                       {"budget": 300, "hard_budget": True, "handoff": self.many("goals", 40)}):  # fmt: skip
            result = self.build(**kwargs)
            report, output = resume.resume(self.root, now=NOW + timedelta(hours=1))
            texts = [result.markdown, json.dumps(result.pack["coverage"]), output, verify.format_text(report)]
            for text in texts:
                self.assertIsNone(CLAIMS.search(text), CLAIMS.search(text))


if __name__ == "__main__":
    unittest.main()
