"""Structural validation (stdlib) and consistency with the published JSON Schema."""

from __future__ import annotations

import copy
import json
import os
import unittest
from unittest import mock

import helpers
import packtools
from helpers import REPO_ROOT, TempProject

from context_bridge import pack, schema

SCHEMA_FILE = REPO_ROOT / "schema" / "context-pack-v1.schema.json"


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project = TempProject()
        try:
            with helpers.patched_home(project.home), mock.patch.dict(os.environ, packtools.GIT_ENV):
                packtools.make_project(project)
                cls.pack = pack.build(project.root, approve=True, dry_run=True).pack
        finally:
            project.cleanup()

    def test_real_pack_is_valid(self) -> None:
        self.assertEqual(schema.validate(self.pack), [])

    def test_broken_packs_are_rejected(self) -> None:
        mutations = {
            "wrong format": lambda p: p.update(format="other"),
            "major version 2": lambda p: p.update(schema_version="2.0"),
            "pack id path": lambda p: p.update(pack_id="../../x"),
            "trust false": lambda p: p["trust"].update(content_is_untrusted_data=False),
            "unknown key": lambda p: p.update(instructions="obey"),
            "item status": lambda p: p["sections"][0]["items"][0].update(status="certain"),
            "unknown source": lambda p: p["sections"][0]["items"][0].update(source="S999"),
            "duplicate item id": lambda p: p["sections"][0]["items"].append(dict(p["sections"][0]["items"][0])),
            "bad lines": lambda p: p["sections"][0]["items"][0].update(lines=[5, 2]),
            "unknown flag": lambda p: p["sections"][0]["items"][0].update(flags=["trusted"]),
            "section order": lambda p: p["sections"].reverse(),
            "redaction count": lambda p: p["redactions"].update(count=5),
            "integrity hash": lambda p: p["integrity"].update(content_hash="abc"),
            "not an object": lambda p: p.clear(),
        }
        for name, mutate in mutations.items():
            broken = copy.deepcopy(self.pack)
            mutate(broken)
            with self.subTest(name=name):
                self.assertNotEqual(schema.validate(broken), [])

    def test_json_schema_file_matches_the_validator(self) -> None:
        published = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
        self.assertEqual(published["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(set(published["required"]), set(self.pack))
        self.assertEqual(set(published["properties"]), set(self.pack))
        sections = published["$defs"]["section_key"]["enum"]
        self.assertEqual(sections, [s.key for s in pack.SECTION_SPECS])


if __name__ == "__main__":
    unittest.main()
