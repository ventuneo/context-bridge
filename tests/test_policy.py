from __future__ import annotations

import os
import unittest

import helpers
from helpers import TempProject

from context_bridge import policy
from context_bridge.policy import DenyRoots, classify, globmatch


class GlobTests(unittest.TestCase):
    def test_double_star(self) -> None:
        self.assertTrue(globmatch("docs/**/*.md", "docs/a.md"))
        self.assertTrue(globmatch("docs/**/*.md", "docs/x/y/a.md"))
        self.assertFalse(globmatch("docs/**/*.md", "src/docs/a.md"))
        self.assertTrue(globmatch("**/README.md", "README.md"))
        self.assertTrue(globmatch("**/README.md", "a/b/README.md"))
        self.assertTrue(globmatch("vendor/**", "vendor/a/b.txt"))

    def test_single_star_stays_in_segment(self) -> None:
        self.assertTrue(globmatch("*.md", "notes.md"))
        self.assertFalse(globmatch("*.md", "docs/notes.md"))
        self.assertTrue(globmatch("file?.txt", "file1.txt"))
        self.assertFalse(globmatch("file?.txt", "file/.txt"))

    def test_case_insensitive_and_literal(self) -> None:
        self.assertTrue(globmatch("README.*", "readme.MD"))
        self.assertFalse(globmatch("a.b", "aXb"))  # the dot is literal


class ClassifyTests(unittest.TestCase):
    def assertDecision(self, rel: str, included: bool, reason_or_kind: str) -> None:
        decision = classify(rel)
        self.assertEqual(decision.included, included, rel)
        self.assertEqual(decision.kind if included else decision.reason, reason_or_kind, rel)

    def test_allowlist_kinds(self) -> None:
        self.assertDecision("README.md", True, "readme")
        self.assertDecision("CLAUDE.md", True, "agent_rules")
        self.assertDecision("sub/AGENTS.md", True, "agent_rules")
        self.assertDecision("pyproject.toml", True, "manifest")
        self.assertDecision("docs/decisions/0001-use-toml.md", True, "decisions")
        self.assertDecision("docs/setup.md", True, "docs")
        self.assertDecision("CONTRIBUTING.md", True, "docs")

    def test_secrets_are_never_allowed(self) -> None:
        for rel in (".env", ".ENV.local", "config/prod.env", "keys/server.key", "deploy/id_ed25519",
                    ".npmrc", "infra/terraform.tfstate", "secrets.yaml", "docs/credentials.md"):  # fmt: skip
            self.assertDecision(rel, False, policy.SECRET_FILE)

    def test_secret_and_noise_directories(self) -> None:
        self.assertDecision(".ssh/config", False, policy.SECRET_DIR)
        self.assertDecision("ops/secrets/README.md", False, policy.SECRET_DIR)
        self.assertDecision("node_modules/pkg/README.md", False, policy.NOISE_DIR)
        self.assertDecision(".context-bridge/latest.md", False, policy.NOISE_DIR)
        self.assertDecision(".git/config", False, policy.NOISE_DIR)

    def test_personal_and_unlisted_files(self) -> None:
        self.assertDecision("CLAUDE.local.md", False, policy.PERSONAL_FILE)
        self.assertDecision("src/app.py", False, policy.NOT_IN_ALLOWLIST)
        self.assertDecision("package-lock.json", False, policy.NOT_IN_ALLOWLIST)

    def test_config_excludes_win_over_allowlist(self) -> None:
        decision = classify("docs/internal/plan.md", exclude=("docs/internal/**",))
        self.assertEqual(decision.reason, policy.EXCLUDED_BY_CONFIG)

    def test_custom_include(self) -> None:
        include = (("notes/*.txt", "custom"),) + policy.DEFAULT_INCLUDE
        self.assertEqual(classify("notes/todo.txt", include=include).kind, "custom")


class DenyRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.private = self.project.base / "private"
        (self.private / "sub").mkdir(parents=True)
        (self.private / "sub" / "file.md").write_text("x", encoding="utf-8", newline="\n")

    def test_blocks_root_inside_and_below(self) -> None:
        deny = DenyRoots([self.private])
        self.assertTrue(deny)
        self.assertTrue(deny.blocks(self.private))
        self.assertTrue(deny.blocks(self.private / "sub" / "file.md"))
        self.assertFalse(deny.blocks(self.project.root))

    @helpers.requires_symlinks
    def test_blocks_through_symlink_and_dotdot(self) -> None:
        deny = DenyRoots([self.private])
        link = self.project.symlink("link", self.private / "sub")
        self.assertTrue(deny.blocks(link))
        self.assertTrue(deny.blocks(self.project.root / ".." / "private" / "sub"))

    def test_blocks_case_variants_on_case_insensitive_fs(self) -> None:
        upper = self.project.base / "PRIVATE"
        if not upper.exists():
            self.skipTest("file system is case-sensitive")
        self.assertTrue(DenyRoots([self.private]).blocks(upper / "sub"))

    def test_missing_deny_roots_are_ignored(self) -> None:
        deny = DenyRoots([self.project.base / "does-not-exist"])
        self.assertFalse(deny)
        self.assertFalse(deny.blocks(self.project.root))

    @helpers.requires_symlinks
    def test_deny_root_given_via_symlink(self) -> None:
        alias = self.project.base / "alias"
        os.symlink(self.private, alias, target_is_directory=True)
        self.assertTrue(DenyRoots([alias]).blocks(self.private / "sub"))


if __name__ == "__main__":
    unittest.main()
