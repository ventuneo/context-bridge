from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest

from helpers import PRIVACY_CHECK, TempProject, isolated_env

_spec = importlib.util.spec_from_file_location("privacy_check", PRIVACY_CHECK)
assert _spec and _spec.loader
privacy_check = importlib.util.module_from_spec(_spec)
sys.modules["privacy_check"] = privacy_check  # dataclasses on 3.11 look the module up here
_spec.loader.exec_module(privacy_check)

# Built at runtime so this file itself never contains a real-looking home path.
HOME_PATH = "/Us" + "ers/jane/projects/x"
NOREPLY = "1+test" + "@users.noreply.github.com"


class CheckTextTests(unittest.TestCase):
    def reasons(self, text: str, terms: list[str] | None = None) -> list[str]:
        return [f.reason for f in privacy_check.check_text(text, "f", terms or [])]

    def test_home_paths_are_flagged(self) -> None:
        self.assertEqual(self.reasons(f"see {HOME_PATH}"), ["absolute home path"])
        self.assertEqual(self.reasons("/ho" + "me/jane/x"), ["absolute home path"])
        self.assertEqual(self.reasons("C:\\Us" + "ers\\jane\\x"), ["absolute home path"])

    def test_placeholder_home_names_are_allowed(self) -> None:
        self.assertEqual(self.reasons("/Us" + "ers/alice/x and /ho" + "me/runner/work"), [])

    def test_emails(self) -> None:
        self.assertEqual(self.reasons("mail jane" + "@gmail.com"), ["e-mail address"])
        self.assertEqual(self.reasons("dev@example.com, ops@service.test, noreply@anthropic.com, " + NOREPLY), [])

    def test_private_terms_case_insensitive(self) -> None:
        self.assertEqual(self.reasons("Project TOPSECRET notes", ["topsecret"]), ["private term 'topsecret'"])


class HookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.project.git_init(commit=False)
        (self.project.root / ".git" / "info").mkdir(exist_ok=True)
        (self.project.root / ".git" / "info" / "private-terms").write_text(
            "# local\nhushhush\n", encoding="utf-8", newline="\n"
        )

    def run_check(self, *args: str, email: str = NOREPLY) -> subprocess.CompletedProcess:
        env = isolated_env(self.project.home)
        env.update(GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_EMAIL=email)
        return subprocess.run(
            [sys.executable, "-I", str(PRIVACY_CHECK), *args],
            cwd=self.project.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def stage(self, rel: str, content: str) -> None:
        self.project.write(rel, content)
        self.project.git("add", rel)

    def test_clean_staged_files_pass(self) -> None:
        self.stage("README.md", "# Demo\nNothing personal here.\n")
        result = self.run_check("--staged")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_home_path_blocks_commit(self) -> None:
        self.stage("notes.md", f"path: {HOME_PATH}\n")
        result = self.run_check("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes.md:1: absolute home path", result.stderr)

    def test_private_term_blocks_commit(self) -> None:
        self.stage("a.txt", "the HushHush project\n")
        result = self.run_check("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("private term 'hushhush'", result.stderr)

    def test_private_term_in_file_name_blocks_commit(self) -> None:
        self.stage("docs/hushhush.md", "ok\n")
        self.assertEqual(self.run_check("--staged").returncode, 1)

    def test_personal_identity_blocks_commit(self) -> None:
        self.stage("README.md", "ok\n")
        result = self.run_check("--staged", email="jane" + "@gmail.com")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no-reply", result.stderr)

    def test_commit_message(self) -> None:
        msg = self.project.root / "MSG"
        msg.write_text("Add feature\n# hushhush in a comment is ignored\n", encoding="utf-8", newline="\n")
        self.assertEqual(self.run_check("--message", str(msg)).returncode, 0)
        msg.write_text("Add hushhush feature\n", encoding="utf-8", newline="\n")
        self.assertEqual(self.run_check("--message", str(msg)).returncode, 1)

    def test_history_finds_leaks_in_old_commits(self) -> None:
        env = isolated_env(self.project.home)
        env.update(GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
        run = lambda *a: subprocess.run(["git", *a], cwd=self.project.root, env=env, check=True, capture_output=True)  # noqa: E731
        self.project.write("old.md", f"{HOME_PATH}\n")
        run("add", "old.md")
        run("commit", "-q", "-m", "leak")
        run("rm", "-q", "old.md")
        run("commit", "-q", "-m", "remove leak")
        self.assertEqual(self.run_check("--all").returncode, 0)  # gone from the index ...
        result = self.run_check("--history")  # ... but still in history
        self.assertEqual(result.returncode, 1)
        self.assertIn("absolute home path", result.stderr)

    def test_history_labels_leftovers_from_blocked_commits(self) -> None:
        self.stage("probe.md", f"{HOME_PATH}\n")  # git add writes the blob even if the commit is blocked
        self.project.git("rm", "-q", "--cached", "probe.md")
        result = self.run_check("--history")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unreachable blob", result.stderr)
        self.assertIn("git gc --prune=now", result.stderr)


if __name__ == "__main__":
    unittest.main()
