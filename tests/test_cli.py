from __future__ import annotations

import unittest

import helpers
from helpers import TempProject

from context_bridge import __version__


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def test_version(self) -> None:
        result = self.project.run_cb("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(__version__, result.stdout)

    def test_no_command_is_usage_error(self) -> None:
        result = self.project.run_cb()
        self.assertEqual(result.returncode, 64)

    def test_unknown_command_is_usage_error(self) -> None:
        result = self.project.run_cb("explode")
        self.assertEqual(result.returncode, 64)
        self.assertIn("invalid choice", result.stderr)

    def test_isolated_mode_ignores_planted_modules(self) -> None:
        # A malicious project could ship json.py next to where the tool runs.
        self.project.write("json.py", "raise SystemExit('planted module executed')\n")
        result = self.project.run_cb("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("planted", result.stdout + result.stderr)


class HomeGuardTests(unittest.TestCase):
    def test_opening_real_home_files_fails(self) -> None:
        probe = helpers._REAL_HOME / "context-bridge-guard-probe-does-not-exist"
        with self.assertRaises(helpers.HomeAccessError):
            open(probe, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
