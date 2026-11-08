"""Platform layer: the Windows behaviour is simulated (windows=True) and runs on every system.

Real Windows runs happen in CI on windows-latest; these tests pin the decisions themselves.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import helpers
import packtools
from helpers import TempProject

from context_bridge import cli, compat, consent, pack, policy, safepath, scan, verify
from context_bridge.config import user_config_path
from context_bridge.errors import UnsafePathError

PROFILE = r"C:\Users\alice"


class FolderTests(unittest.TestCase):
    def test_windows_uses_the_user_profile_not_a_git_bash_home(self) -> None:
        env = {"HOME": "/c/Users/alice", "USERPROFILE": PROFILE}
        self.assertEqual(compat.home(env, windows=True), Path(PROFILE))
        self.assertEqual(compat.home(env, windows=False), Path("/c/Users/alice"))

    def test_windows_folders_for_state_and_configuration(self) -> None:
        env = {
            "USERPROFILE": PROFILE,
            "LOCALAPPDATA": PROFILE + r"\AppData\Local",
            "APPDATA": PROFILE + r"\AppData\Roaming",
        }
        self.assertEqual(compat.state_home(env, windows=True), Path(env["LOCALAPPDATA"]))
        self.assertEqual(compat.config_home(env, windows=True), Path(env["APPDATA"]))
        posix = {"HOME": "/home/alice"}
        self.assertEqual(compat.state_home(posix, windows=False), Path("/home/alice/.local/state"))
        self.assertEqual(compat.config_home(posix, windows=False), Path("/home/alice/.config"))

    def test_xdg_variables_win_everywhere(self) -> None:
        env = {"XDG_STATE_HOME": "/x/state", "XDG_CONFIG_HOME": "/x/config", "LOCALAPPDATA": "L", "APPDATA": "A"}
        for windows in (True, False):
            self.assertEqual(compat.state_home(env, windows=windows), Path("/x/state"))
            self.assertEqual(compat.config_home(env, windows=windows), Path("/x/config"))

    def test_consent_and_config_use_these_folders(self) -> None:
        env = {"XDG_STATE_HOME": "/x/state", "XDG_CONFIG_HOME": "/x/config"}
        self.assertEqual(consent.state_dir(env), Path("/x/state/context-bridge/consent"))
        self.assertEqual(user_config_path(env), Path("/x/config/context-bridge/config.toml"))

    @unittest.skipIf(compat.WINDOWS, "the key is case-insensitive on Windows")
    def test_approvals_from_older_versions_are_still_found_on_posix(self) -> None:
        root = Path("/srv/project")
        old_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
        self.assertEqual(consent.consent_path(root, {"XDG_STATE_HOME": "/s"}).stem, old_key)


class WindowsNameTests(unittest.TestCase):
    def test_device_names_streams_and_trailing_dots_are_refused_on_windows(self) -> None:
        for rel in ("CON", "nul.txt", "docs/Aux.md", "COM1.log", "lpt9", "conout$", "notes.md:secret", "a?.md",
                    "draft.", "space ", 'q"uote.md', "pipe|x", "tab\tname.md"):  # fmt: skip
            with self.subTest(rel=rel), self.assertRaises(UnsafePathError):
                safepath.check_relative(rel, windows=True)

    def test_ordinary_names_pass_on_windows(self) -> None:
        for rel in ("README.md", "docs/console.md", "nullable.md", "com10.md", "docs/a.b.c.md", "CONTRIBUTING.md"):
            with self.subTest(rel=rel):
                self.assertEqual(str(safepath.check_relative(rel, windows=True)), rel)

    def test_posix_keeps_accepting_colons(self) -> None:
        self.assertEqual(str(safepath.check_relative("notes:2026.md", windows=False)), "notes:2026.md")


class LinkTests(unittest.TestCase):
    @staticmethod
    def entry(tag: int) -> SimpleNamespace:
        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_reparse_tag=tag)

    def test_junctions_count_as_links_but_cloud_placeholders_do_not(self) -> None:
        with mock.patch("context_bridge.compat.os.lstat", return_value=self.entry(0xA0000003)):
            self.assertTrue(compat.is_link_like("junction"))
        with mock.patch("context_bridge.compat.os.lstat", return_value=self.entry(0x9000001A)):  # OneDrive file
            self.assertFalse(compat.is_link_like("placeholder"))

    @helpers.requires_symlinks
    def test_real_links_files_and_missing_paths(self) -> None:
        with TempProject() as project:
            target = project.write("a.md", "x")
            link = project.symlink("b.md", target)
            self.assertTrue(compat.is_link_like(link))
            self.assertFalse(compat.is_link_like(target))
            self.assertFalse(compat.is_link_like(project.root / "missing"))

    def test_scan_skips_directory_junctions(self) -> None:
        with TempProject() as project:
            project.write("docs/a.md", "# A\n")
            project.write("linked/b.md", "# B\n")
            real = compat.is_link_like
            fake = lambda path: Path(path).name == "linked" or real(path)  # noqa: E731
            with helpers.patched_home(project.home), mock.patch("context_bridge.compat.is_link_like", side_effect=fake):
                report = scan.scan(project.root)
        self.assertIn("linked/", report.excluded.get(scan.SYMLINKED_DIRECTORY, []))
        self.assertNotIn("linked/b.md", [f.path for f in report.included])

    def test_a_junction_cannot_become_the_pack_store(self) -> None:
        with TempProject() as project:
            store = project.root / ".context-bridge"
            store.mkdir()
            with (
                mock.patch("context_bridge.compat.is_link_like", return_value=True),
                self.assertRaises(UnsafePathError),
            ):
                safepath.ensure_private_dir(store)


class PathKeyTests(unittest.TestCase):
    def test_windows_keys_ignore_case_and_slash_direction(self) -> None:
        self.assertEqual(
            compat.path_key("C:/Users/Alice/Proj", windows=True), compat.path_key(r"c:\users\alice\proj", windows=True)
        )
        self.assertNotEqual(compat.path_key("/Proj", windows=False), compat.path_key("/proj", windows=False))

    def test_deny_roots_without_file_ids_fall_back_to_the_resolved_path(self) -> None:
        with TempProject() as project:
            denied = project.root / "private"
            denied.mkdir()
            project.write("README.md", "x")
            real_stat = os.stat

            def no_file_ids(path: object, *args: object, **kwargs: object) -> SimpleNamespace:
                st = real_stat(path, *args, **kwargs)  # type: ignore[arg-type]
                return SimpleNamespace(st_dev=st.st_dev, st_ino=0, st_mode=st.st_mode)

            with mock.patch("context_bridge.policy.os.stat", side_effect=no_file_ids):
                deny = policy.DenyRoots([denied])
                self.assertTrue(deny.blocks(denied / "notes.md"))
                self.assertFalse(deny.blocks(project.root / "README.md"))


class ReplaceTests(unittest.TestCase):
    def test_windows_retries_while_another_process_holds_the_file(self) -> None:
        with mock.patch("context_bridge.compat.os.replace", side_effect=[PermissionError, PermissionError, None]) as replace, \
                mock.patch("context_bridge.compat.time.sleep"):  # fmt: skip
            compat.replace("a", "b", windows=True)
        self.assertEqual(replace.call_count, 3)

    def test_posix_does_not_retry_and_windows_gives_up_eventually(self) -> None:
        with mock.patch("context_bridge.compat.os.replace", side_effect=PermissionError) as replace:
            with self.assertRaises(PermissionError):
                compat.replace("a", "b", windows=False)
            self.assertEqual(replace.call_count, 1)
        with mock.patch("context_bridge.compat.os.replace", side_effect=PermissionError) as replace, \
                mock.patch("context_bridge.compat.time.sleep"), self.assertRaises(PermissionError):  # fmt: skip
            compat.replace("a", "b", windows=True, attempts=3)
        self.assertEqual(replace.call_count, 3)


class PermissionTests(unittest.TestCase):
    @helpers.requires_posix_permissions
    def test_permissions_enforced_reads_the_real_mode(self) -> None:
        with TempProject() as project:
            os.chmod(project.root, 0o700)
            self.assertTrue(compat.permissions_enforced(project.root, 0o700))
            os.chmod(project.root, 0o755)
            self.assertFalse(compat.permissions_enforced(project.root, 0o700))
        self.assertTrue(compat.permissions_enforced("anything", 0o700, windows=True))

    def test_pack_warns_when_the_file_system_ignores_permissions(self) -> None:
        # Simulates a Windows drive mounted in WSL, where chmod has no effect.
        with (
            TempProject() as project,
            helpers.patched_home(project.home),
            mock.patch.dict(os.environ, packtools.GIT_ENV),
        ):
            packtools.make_project(project)
            out = io.StringIO()
            with (
                mock.patch("context_bridge.compat.permissions_enforced", return_value=False),
                contextlib.redirect_stdout(out),
            ):
                code = cli.main(["pack", "--root", str(project.root), "--approve"])
        self.assertEqual(code, 1)
        self.assertIn("this file system ignores file permissions", out.getvalue())


class LineEndingTests(unittest.TestCase):
    """Windows checkouts often have CRLF line endings (git with core.autocrlf=true)."""

    @staticmethod
    def build(newline: bytes) -> tuple[list[tuple[str, list[str]]], int]:
        with (
            TempProject() as project,
            helpers.patched_home(project.home),
            mock.patch.dict(os.environ, packtools.GIT_ENV),
        ):
            packtools.make_project(project)
            for path in [p for p in project.root.rglob("*") if p.is_file()]:
                path.write_bytes(path.read_bytes().replace(b"\n", newline))
            result = pack.build(project.root, approve=True)
            code = verify.verify(project.root).exit_code
        return [(s["key"], [i["text"] for i in s["items"]]) for s in result.pack["sections"]], code

    def test_crlf_sources_give_the_same_items_and_the_pack_verifies(self) -> None:
        lf, lf_code = self.build(b"\n")
        crlf, crlf_code = self.build(b"\r\n")
        self.assertTrue(lf)
        self.assertEqual(crlf, lf)
        self.assertEqual((lf_code, crlf_code), (0, 0))
        self.assertFalse(any("\r" in text for _, texts in crlf for text in texts))


class OutputTests(unittest.TestCase):
    def test_utf8_stdio_turns_a_code_page_stream_into_utf8(self) -> None:
        raw = io.BytesIO()
        stdout, stderr = io.TextIOWrapper(raw, encoding="cp1252"), io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            compat.utf8_stdio()
            sys.stdout.write("⚠ → ·")
            sys.stdout.flush()
        self.assertEqual(raw.getvalue(), "⚠ → ·".encode())


if __name__ == "__main__":
    unittest.main()
