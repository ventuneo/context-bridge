from __future__ import annotations

import json
import unittest

from helpers import TempProject

from context_bridge.handoff import MAX_HANDOFF_BYTES, HandoffError, parse


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def parse(self, data: object) -> tuple[list, list[str], str | None]:
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        return parse(raw, self.project.root, "S9")

    def test_full_handoff(self) -> None:
        items, warnings, author = self.parse(
            {
                "goal": {"text": "Ship v1", "status": "fact"},
                "status": {"text": "pack works", "status": "fact"},
                "done": ["scan"],
                "constraints": [{"text": "No network", "status": "fact"}],
                "decisions": [{"text": "Use TOML", "reason": "readable", "status": "fact"}],
                "next_steps": [{"text": "Write verify", "status": "fact"}],
                "open_questions": [{"text": "Windows?", "status": "uncertain"}],
                "files_touched": ["src/a.py", str(self.project.root / "src" / "b.py")],
                "author": "assistant",
            }
        )
        self.assertEqual(warnings, [])
        self.assertEqual(author, "assistant")
        self.assertEqual(
            [(i.section, i.text, i.status) for i in items],
            [("goals", "Ship v1", "fact"), ("state", "Status: pack works", "fact"),
             ("state", "Done: scan", "uncertain"), ("constraints", "No network", "fact"),
             ("decisions", "Use TOML (reason: readable)", "fact"), ("next_steps", "Write verify", "fact"),
             ("open_questions", "Windows?", "uncertain"),
             ("state", "Files touched in the session: src/a.py, src/b.py", "fact")],
        )  # fmt: skip
        self.assertEqual(items[2].flags, ["unlabeled"])
        self.assertTrue(all(i.origin_rank == 0 and i.source == "S9" for i in items))

    def test_files_outside_the_project_are_dropped(self) -> None:
        items, warnings, _ = self.parse({"files_touched": ["/etc/hosts", "../x", "~/notes.md", "ok.md"]})
        self.assertEqual(items[0].text, "Files touched in the session: ok.md")
        self.assertEqual(len(warnings), 3)

    def test_unknown_fields_warn(self) -> None:
        _items, warnings, _ = self.parse({"mood": "great"})
        self.assertEqual(warnings, ["handoff: unknown field 'mood' ignored"])

    def test_invalid_input_is_rejected(self) -> None:
        bad = [
            b"not json",
            b"\xff\xfe",
            ["a list"],
            {"next_steps": "not a list"},
            {"next_steps": [{"text": "x", "status": "sure"}]},
            {"next_steps": [{"text": "x", "status": "fact", "extra": 1}]},
            {"next_steps": [{"status": "fact"}]},
            {"next_steps": [""]},
            {"next_steps": ["x" * 1001]},
            {"next_steps": ["x"] * 51},
            {"decisions": [{"text": "x", "status": "fact", "reason": 5}]},
            {"files_touched": "a.py"},
            {"author": ""},
        ]
        for data in bad:
            with self.assertRaises(HandoffError, msg=repr(data)[:60]):
                self.parse(data)

    def test_size_limit(self) -> None:
        with self.assertRaises(HandoffError):
            self.parse(b"{" + b" " * MAX_HANDOFF_BYTES + b"}")


if __name__ == "__main__":
    unittest.main()
