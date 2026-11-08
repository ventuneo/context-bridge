from __future__ import annotations

import unittest
from pathlib import Path

import helpers
from helpers import TempProject

from context_bridge import config
from context_bridge.config import Config, load_config, user_config_path
from context_bridge.errors import ConfigError


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.user_path = self.project.home / ".config" / "context-bridge" / "config.toml"

    def write_user(self, text: str) -> None:
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_path.write_text(text, encoding="utf-8")

    def write_project(self, text: str) -> None:
        self.project.write(config.PROJECT_CONFIG_REL, text)

    def load(self) -> Config:
        return load_config(self.project.root, self.user_path)


class LayeringTests(ConfigTestCase):
    def test_defaults_without_files(self) -> None:
        cfg = self.load()
        self.assertEqual(cfg.deny_roots, ())
        self.assertTrue(cfg.redact_pii)
        self.assertEqual(cfg.max_file_bytes, config.DEFAULT_MAX_FILE_BYTES)
        self.assertFalse(cfg.project_config_loaded)
        self.assertEqual(cfg.warnings, ())

    def test_user_config(self) -> None:
        private = self.project.base / "private"
        self.write_user(
            f'[privacy]\ndeny_roots = ["{private}"]\nallowed_external_roots = ["{self.project.base}/notes"]\n'
            'redact_pii = false\n[scan]\nmax_file_bytes = 1000\nexclude = ["drafts/**"]\n'
        )
        cfg = self.load()
        self.assertEqual(cfg.deny_roots, (private,))
        self.assertEqual(cfg.allowed_external_roots, (self.project.base / "notes",))
        self.assertFalse(cfg.redact_pii)
        self.assertEqual(cfg.max_file_bytes, 1000)
        self.assertEqual(cfg.exclude, ("drafts/**",))

    def test_user_paths_expand_home(self) -> None:
        self.write_user('[privacy]\ndeny_roots = ["~/secret-stuff"]\n')
        from helpers import patched_home

        with patched_home(self.project.home):
            cfg = self.load()
        self.assertEqual(cfg.deny_roots, (self.project.home / "secret-stuff",))


class ProjectCannotLoosenTests(ConfigTestCase):
    def test_project_cannot_set_deny_or_external_roots(self) -> None:
        self.write_user(f'[privacy]\ndeny_roots = ["{self.project.base}/private"]\n')
        self.write_project('[privacy]\ndeny_roots = []\nallowed_external_roots = ["/"]\n')
        cfg = self.load()
        self.assertEqual(cfg.deny_roots, (self.project.base / "private",))
        self.assertEqual(cfg.allowed_external_roots, ())
        self.assertEqual(len([w for w in cfg.warnings if "only allowed in the user config" in w]), 2)

    def test_project_can_only_lower_limits(self) -> None:
        self.write_project("[scan]\nmax_file_bytes = 9999999\nmax_total_bytes = 1000\n")
        cfg = self.load()
        self.assertEqual(cfg.max_file_bytes, config.DEFAULT_MAX_FILE_BYTES)
        self.assertEqual(cfg.max_total_bytes, 1000)
        self.assertTrue(any("can only be lowered" in w for w in cfg.warnings))

    def test_project_cannot_disable_pii_redaction(self) -> None:
        self.write_project("[privacy]\nredact_pii = false\n")
        cfg = self.load()
        self.assertTrue(cfg.redact_pii)
        self.assertTrue(any("can only be switched on" in w for w in cfg.warnings))

    def test_project_can_enable_pii_when_user_disabled_it(self) -> None:
        self.write_user("[privacy]\nredact_pii = false\n")
        self.write_project("[privacy]\nredact_pii = true\n")
        self.assertTrue(self.load().redact_pii)

    def test_project_additions(self) -> None:
        self.write_user('[scan]\nexclude = ["a/**"]\n')
        self.write_project('[scan]\nexclude = ["b/**"]\ninclude = ["notes/*.txt"]\n[sources]\nexternal = ["~/n.md"]\n')
        cfg = self.load()
        self.assertEqual(cfg.exclude, ("a/**", "b/**"))
        self.assertEqual(cfg.include[0], ("notes/*.txt", "custom"))
        self.assertEqual(len(cfg.external_sources), 1)
        self.assertTrue(cfg.project_config_loaded)

    @helpers.requires_symlinks
    def test_symlinked_project_config_is_refused(self) -> None:
        outside = self.project.base / "elsewhere.toml"
        outside.write_text("[scan]\n", encoding="utf-8")
        self.project.symlink(config.PROJECT_CONFIG_REL, outside)
        with self.assertRaises(ConfigError):
            self.load()


class ValidationTests(ConfigTestCase):
    def test_invalid_toml(self) -> None:
        self.write_project("[scan\n")
        with self.assertRaises(ConfigError):
            self.load()

    def test_wrong_types_and_bounds(self) -> None:
        for text in ('[scan]\nexclude = "x"\n', "[scan]\nmax_file_bytes = 0\n", "[scan]\nmax_file_bytes = true\n",
                     '[privacy]\nredact_pii = "yes"\n'):  # fmt: skip
            self.write_user(text)
            with self.assertRaises(ConfigError, msg=text):
                self.load()

    def test_unknown_keys_warn(self) -> None:
        self.write_user("[scan]\nfollow_symlinks = true\n[extra]\nx = 1\n")
        cfg = self.load()
        self.assertEqual(len(cfg.warnings), 2)


class UserConfigPathTests(unittest.TestCase):
    def test_resolution_order(self) -> None:
        self.assertEqual(user_config_path({"CONTEXT_BRIDGE_CONFIG": "/tmp/x.toml"}), Path("/tmp/x.toml"))
        self.assertEqual(
            user_config_path({"XDG_CONFIG_HOME": "/cfg", "HOME": "/h"}), Path("/cfg/context-bridge/config.toml")
        )
        self.assertEqual(user_config_path({"HOME": "/h"}), Path("/h/.config/context-bridge/config.toml"))


if __name__ == "__main__":
    unittest.main()
