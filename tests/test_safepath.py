from __future__ import annotations

import hashlib
import os
import stat
import unittest

import helpers
from helpers import TempProject

from context_bridge import safepath
from context_bridge.errors import UnsafePathError
from context_bridge.safepath import atomic_write, check_relative, decode_text, ensure_private_dir, read_file


class SafePathTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.root = self.project.root
        self.outside = self.project.base / "outside.txt"
        self.outside.write_text("outside secret", encoding="utf-8")

    def assertReason(self, rel: str, reason: str, max_bytes: int = 1024) -> None:
        with self.assertRaises(UnsafePathError) as ctx:
            read_file(self.root, rel, max_bytes)
        self.assertEqual(ctx.exception.reason, reason, rel)


class CheckRelativeTests(SafePathTestCase):
    def test_rejects_dangerous_paths(self) -> None:
        for rel in ("", "/etc/passwd", "../x", "a/../../x", "~/x", "C:/x", "a\\b", "a\x00b"):
            with self.assertRaises(UnsafePathError, msg=repr(rel)):
                check_relative(rel)

    def test_accepts_clean_paths(self) -> None:
        self.assertEqual(str(check_relative("docs/a.md")), "docs/a.md")


class ReadFileTests(SafePathTestCase):
    def test_reads_regular_file(self) -> None:
        self.project.write("docs/a.md", "hello")
        content = read_file(self.root, "docs/a.md", 1024)
        self.assertEqual(content.data, b"hello")
        self.assertEqual(content.sha256, hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(content.size, 5)
        self.assertFalse(content.via_symlink)

    @helpers.requires_symlinks
    def test_symlink_inside_root_is_allowed(self) -> None:
        self.project.write("real.md", "inside")
        self.project.symlink("alias.md", "real.md")
        content = read_file(self.root, "alias.md", 1024)
        self.assertEqual(content.data, b"inside")
        self.assertTrue(content.via_symlink)

    @helpers.requires_symlinks
    def test_symlink_escaping_root_is_refused(self) -> None:
        self.project.symlink("evil.md", self.outside)
        self.assertReason("evil.md", safepath.SYMLINK_OUTSIDE_ROOT)

    @helpers.requires_symlinks
    def test_directory_symlink_escaping_root_is_refused(self) -> None:
        self.project.symlink("linkdir", self.project.base)
        self.assertReason("linkdir/outside.txt", safepath.SYMLINK_OUTSIDE_ROOT)

    @helpers.requires_symlinks
    def test_broken_symlink_and_loop(self) -> None:
        self.project.symlink("broken.md", "nowhere.md")
        self.assertReason("broken.md", safepath.BROKEN_SYMLINK)
        self.project.symlink("loop_a", "loop_b")
        self.project.symlink("loop_b", "loop_a")
        self.assertReason("loop_a", safepath.BROKEN_SYMLINK)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_fifo_is_refused_without_blocking(self) -> None:
        os.mkfifo(self.root / "pipe.md")
        self.assertReason("pipe.md", safepath.NOT_REGULAR_FILE)

    def test_directory_is_refused(self) -> None:
        (self.root / "folder.md").mkdir()
        self.assertReason("folder.md", safepath.NOT_REGULAR_FILE)

    def test_size_limit(self) -> None:
        self.project.write("big.md", "x" * 2048)
        self.assertReason("big.md", safepath.TOO_LARGE, max_bytes=1024)

    def test_missing_and_invalid(self) -> None:
        self.assertReason("nope.md", safepath.MISSING)
        self.assertReason("../outside.txt", safepath.INVALID_PATH)


class TextTests(unittest.TestCase):
    def test_binary_detection(self) -> None:
        self.assertTrue(safepath.is_binary(b"PNG\x00\x01"))
        self.assertFalse(safepath.is_binary("Grüezi".encode()))

    def test_decode_strips_bom_and_reports_invalid_utf8(self) -> None:
        self.assertEqual(decode_text("\ufeffhi".encode()), ("hi", True))
        text, valid = decode_text(b"caf\xe9")
        self.assertFalse(valid)
        self.assertEqual(text, "caf\ufffd")


class WriteTests(SafePathTestCase):
    def test_atomic_write_sets_mode_and_leaves_no_temp(self) -> None:
        target = self.root / "out.json"
        atomic_write(target, b"{}")
        atomic_write(target, b'{"a": 1}')
        self.assertEqual(target.read_bytes(), b'{"a": 1}')
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["out.json"])

    @helpers.requires_symlinks
    def test_atomic_write_replaces_symlink_instead_of_following_it(self) -> None:
        link = self.project.symlink("out.json", self.outside)
        atomic_write(link, b"new")
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "outside secret")
        self.assertFalse(link.is_symlink())

    @helpers.requires_symlinks
    def test_private_dir(self) -> None:
        store = self.root / ".context-bridge"
        ensure_private_dir(store)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(store.stat().st_mode), 0o700)
        evil = self.root / ".evil-store"
        evil.symlink_to(self.project.base, target_is_directory=True)
        with self.assertRaises(UnsafePathError):
            ensure_private_dir(evil)


class RootTests(SafePathTestCase):
    def test_resolve_root(self) -> None:
        self.assertEqual(safepath.resolve_root(self.root), self.root)
        with self.assertRaises(UnsafePathError):
            safepath.resolve_root(self.root / "missing")
        with self.assertRaises(UnsafePathError):
            safepath.resolve_root(self.outside)


if __name__ == "__main__":
    unittest.main()
