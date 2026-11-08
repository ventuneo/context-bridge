from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

from helpers import TempProject, isolated_env, patched_home

from context_bridge import gitrun


class GitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.enterContext(patched_home(self.project.home))
        self.enterContext(mock.patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}))


class InspectTests(GitTestCase):
    def test_not_a_repo(self) -> None:
        status = gitrun.inspect(self.project.root)
        self.assertEqual((status.usable, status.reason), (False, gitrun.NOT_A_REPO))

    def test_clean_repo_is_usable(self) -> None:
        self.project.git_init()
        self.assertTrue(gitrun.inspect(self.project.root).usable)

    def test_git_not_installed(self) -> None:
        with mock.patch("context_bridge.gitrun.shutil.which", return_value=None):
            self.assertEqual(gitrun.inspect(self.project.root).reason, gitrun.NOT_INSTALLED)

    def test_fsmonitor_false_is_fine(self) -> None:
        self.project.git_init()
        self.project.git("config", "core.fsmonitor", "false")
        self.assertTrue(gitrun.inspect(self.project.root).usable)

    def test_dangerous_local_config_disables_git(self) -> None:
        self.project.git_init()
        for key, value in (("filter.evil.clean", "touch pwned"), ("diff.x.textconv", "cat"),
                           ("gpg.program", "evil"), ("include.path", "../other.cfg"), ("core.pager", "less")):  # fmt: skip
            self.project.git("config", key, value)
        status = gitrun.inspect(self.project.root)
        self.assertFalse(status.usable)
        self.assertEqual(status.reason, gitrun.UNTRUSTED_CONFIG)
        self.assertEqual(
            set(status.untrusted_keys),
            {"filter.evil.clean", "diff.x.textconv", "gpg.program", "include.path", "core.pager"},
        )


class FsmonitorTests(GitTestCase):
    def test_fsmonitor_hook_never_runs(self) -> None:
        self.project.git_init()
        marker = self.project.base / "fsmonitor-ran"
        hook = self.project.base / "hook.sh"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)
        self.project.git("config", "core.fsmonitor", str(hook))
        # Sanity check: plain git really runs the hook, so the test is meaningful.
        subprocess.run(["git", "status"], cwd=self.project.root, env=isolated_env(self.project.home),
                       capture_output=True, check=False)  # fmt: skip
        if not marker.exists():
            self.skipTest("this git version does not run the fsmonitor hook on status")
        marker.unlink()
        status = gitrun.inspect(self.project.root)
        self.assertEqual(status.reason, gitrun.UNTRUSTED_CONFIG)
        gitrun.run_git(self.project.root, ["status", "--porcelain"])  # even a direct call is protected
        gitrun.list_files(self.project.root)
        self.assertFalse(marker.exists())


class ListFilesTests(GitTestCase):
    def test_respects_gitignore_and_includes_untracked(self) -> None:
        self.project.write(".gitignore", "ignored.md\nbuild/\n")
        self.project.write("README.md", "# x")
        self.project.write("ignored.md", "no")
        self.project.write("build/out.md", "no")
        self.project.git_init()
        self.project.write("new.md", "untracked but not ignored")
        files = gitrun.list_files(self.project.root)
        self.assertEqual(sorted(files), [".gitignore", "README.md", "new.md"])

    def test_paths_are_relative_to_a_subdirectory_root(self) -> None:
        self.project.write("README.md", "# x")
        self.project.write("pkg/docs/a.md", "a")
        self.project.git_init()
        self.assertEqual(gitrun.list_files(self.project.root / "pkg"), ["docs/a.md"])

    def test_redirecting_environment_is_ignored(self) -> None:
        self.project.write("README.md", "# x")
        self.project.git_init()
        other = TempProject()
        self.addCleanup(other.cleanup)
        other.write("OTHER.md", "y")
        other.git_init()
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other.root / ".git"), "GIT_WORK_TREE": str(other.root)}):
            self.assertEqual(gitrun.list_files(self.project.root), ["README.md"])

    def test_unicode_file_names(self) -> None:
        self.project.write("docs/Übersicht.md", "x")
        self.project.git_init()
        self.assertEqual(gitrun.list_files(self.project.root), ["docs/Übersicht.md"])


if __name__ == "__main__":
    unittest.main()
