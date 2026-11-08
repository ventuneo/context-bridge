from __future__ import annotations

import json
import os
import stat
import unittest

import helpers
from helpers import TempProject, patched_home

from context_bridge import consent, store
from context_bridge.errors import UnsafePathError


class ConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.enterContext(patched_home(self.project.home))

    def test_record_lives_outside_the_project(self) -> None:
        path = consent.consent_path(self.project.root)
        self.assertTrue(str(path).startswith(str(self.project.home / ".local" / "state" / "context-bridge")))
        self.assertFalse(str(path).startswith(str(self.project.root)))

    def test_approve_save_load_and_pending(self) -> None:
        record = consent.load(self.project.root)
        self.assertFalse(record.exists)
        record.approve(["README.md"], ["git"], "2026-11-07T10:00:00Z")
        consent.save(record)
        loaded = consent.load(self.project.root)
        self.assertTrue(loaded.exists)
        self.assertEqual(loaded.pending(["README.md", "docs/new.md"], ["git", "file_list"]),
                         (["docs/new.md"], ["file_list"]))  # fmt: skip
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(loaded.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(loaded.path.parent.stat().st_mode), 0o700)

    def test_a_repository_cannot_ship_its_own_approval(self) -> None:
        fake = {"format": consent.CONSENT_FORMAT, "files": {"README.md": "x"}, "pseudo": {"git": "x"}}
        self.project.write(".context-bridge/consent.json", json.dumps(fake))
        self.project.write("consent.json", json.dumps(fake))
        self.assertFalse(consent.load(self.project.root).exists)

    def test_moved_project_needs_new_approval(self) -> None:
        record = consent.load(self.project.root)
        record.approve(["README.md"], [], "t")
        consent.save(record)
        moved = self.project.base / "moved"
        self.project.root.rename(moved)
        self.assertFalse(consent.load(moved).exists)

    def test_corrupt_record_is_an_error(self) -> None:
        path = consent.consent_path(self.project.root)
        path.parent.mkdir(parents=True)
        for content in (b"{broken", b'{"format": "other"}', b'{"format": "context-bridge.consent", "files": []}'):
            path.write_bytes(content)
            with self.assertRaises(consent.ConsentError):
                consent.load(self.project.root)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.root = self.project.root

    def write(self, pack_id: str, keep: int = 10) -> dict:
        return store.write_pack(self.root, pack_id, b'{"pack": 1}\n', b"# pack\n", keep)

    def test_layout_permissions_and_self_ignore(self) -> None:
        paths = self.write("20261107T100000Z-abcdef")
        base = self.root / ".context-bridge"
        self.assertEqual((base / ".gitignore").read_bytes(), store.GITIGNORE)
        self.assertEqual((self.root / paths["json"]).read_bytes(), b'{"pack": 1}\n')
        self.assertEqual((base / "latest.md").read_bytes(), b"# pack\n")
        if os.name == "posix":
            for directory in (base, base / "packs"):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for name in (".gitignore", "latest.json", "latest.md"):
                self.assertEqual(stat.S_IMODE((base / name).stat().st_mode), 0o600)
        self.assertFalse((self.root / ".gitignore").exists())  # the project's own .gitignore is untouched

    def test_git_ignores_the_store(self) -> None:
        self.project.write("README.md", "# x\n")
        self.project.git_init()
        self.write("20261107T100000Z-abcdef")
        self.assertEqual(self.project.git("status", "--porcelain").stdout, "")

    @helpers.requires_symlinks
    def test_symlinked_store_is_refused(self) -> None:
        elsewhere = self.project.base / "elsewhere"
        elsewhere.mkdir()
        self.project.symlink(".context-bridge", elsewhere)
        with self.assertRaises(UnsafePathError):
            self.write("20261107T100000Z-abcdef")
        self.assertEqual(list(elsewhere.iterdir()), [])

    @helpers.requires_symlinks
    def test_latest_symlink_is_replaced_not_followed(self) -> None:
        self.write("20261107T100000Z-abcdef")
        target = self.project.base / "victim.md"
        target.write_text("keep me", encoding="utf-8", newline="\n")
        latest = self.root / ".context-bridge" / "latest.md"
        latest.unlink()
        latest.symlink_to(target)
        self.write("20261107T100001Z-abcdef")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me")
        self.assertFalse(latest.is_symlink())

    def test_retention_deletes_only_old_pack_files(self) -> None:
        for second in range(5):
            self.write(f"20261107T10000{second}Z-abcdef", keep=3)
        packs = self.root / ".context-bridge" / "packs"
        (packs / "notes.txt").write_text("not a pack", encoding="utf-8", newline="\n")
        self.write("20261107T100009Z-abcdef", keep=3)
        names = sorted(p.name for p in packs.iterdir())
        self.assertEqual(
            names,
            ["20261107T100003Z-abcdef.json", "20261107T100003Z-abcdef.md", "20261107T100004Z-abcdef.json",
             "20261107T100004Z-abcdef.md", "20261107T100009Z-abcdef.json", "20261107T100009Z-abcdef.md",
             "notes.txt"],
        )  # fmt: skip

    def test_invalid_pack_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.write("../../escape")


if __name__ == "__main__":
    unittest.main()
