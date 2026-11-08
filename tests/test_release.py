"""Release hygiene: one version everywhere, community files, working links, pinned CI, the demo project."""

from __future__ import annotations

import json
import os
import re
import tomllib
import unittest
from unittest import mock

import helpers
import packtools
from helpers import REPO_ROOT, TempProject

from context_bridge import __version__, pack, resume, verify

DOCS = sorted(
    [*REPO_ROOT.glob("*.md"), *(REPO_ROOT / "docs").glob("*.md"), *(REPO_ROOT / "skills").rglob("*.md"),
     *(REPO_ROOT / ".github").rglob("*.md"), *(REPO_ROOT / "examples").rglob("*.md")]
)  # fmt: skip
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """GitHub's anchor for a Markdown heading."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


class VersionTests(unittest.TestCase):
    def test_one_version_everywhere(self) -> None:
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["version"], __version__)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")  # a release version, not a .dev one
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", changelog)
        self.assertIn(
            f"[{__version__}]: https://github.com/ventuneo/context-bridge/releases/tag/v{__version__}", changelog
        )

    def test_install_commands_clone_the_current_tag(self) -> None:
        for name in ("README.md", "docs/install.md"):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            tags = set(re.findall(r"git clone --branch (\S+)", text))
            with self.subTest(file=name):
                self.assertEqual(tags, {f"v{__version__}"})

    def test_python_versions_match_the_ci_matrix(self) -> None:
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["requires-python"], ">=3.11")
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('python: ["3.11", "3.12", "3.13", "3.14", "3.15"]', ci)
        self.assertIn("os: [ubuntu-latest, macos-latest]", ci)


class CommunityFileTests(unittest.TestCase):
    def test_community_files_exist(self) -> None:
        for name in ("README.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                     "docs/install.md", "docs/setup.md", "docs/limitations.md", "docs/quality.md",
                     "docs/release-checklist.md", ".github/pull_request_template.md", ".github/dependabot.yml",
                     ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
                     ".github/ISSUE_TEMPLATE/config.yml"):  # fmt: skip
            with self.subTest(file=name):
                self.assertGreater((REPO_ROOT / name).stat().st_size, 100)

    def test_mit_license_without_a_personal_name(self) -> None:
        text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n\nCopyright (c) 2026 The Context Bridge contributors\n"))
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND', text)

    def test_no_plugin_marketplace_packaging(self) -> None:
        # Context Bridge is distributed through its GitHub repository only.
        self.assertFalse((REPO_ROOT / ".claude-plugin").exists())


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self) -> None:
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, anchor = target.partition("#")
                resolved = (doc.parent / path).resolve() if path else doc
                with self.subTest(doc=str(doc.relative_to(REPO_ROOT)), link=target):
                    self.assertTrue(resolved.exists())
                    if anchor and resolved.suffix == ".md":
                        headings = re.findall(r"^#+ (.+)$", resolved.read_text(encoding="utf-8"), re.MULTILINE)
                        self.assertIn(anchor, {slug(h) for h in headings})

    def test_docs_contain_no_home_paths(self) -> None:
        for doc in DOCS:
            with self.subTest(doc=str(doc.relative_to(REPO_ROOT))):
                self.assertNotRegex(doc.read_text(encoding="utf-8"), r"/Users/[a-z]|/home/[a-z]")


class WorkflowTests(unittest.TestCase):
    def test_actions_are_pinned_and_least_privilege(self) -> None:
        for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
            text = workflow.read_text(encoding="utf-8")
            uses = re.findall(r"uses: (\S+)", text)
            with self.subTest(workflow=workflow.name):
                self.assertTrue(uses)
                for action in uses:
                    self.assertRegex(action, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
                self.assertIn("permissions:\n  contents: read", text)
                self.assertEqual(text.count("persist-credentials: false"), text.count("actions/checkout@"))


class DemoProjectTests(unittest.TestCase):
    """The README demo is produced from examples/demo-project; it must keep working as shown."""

    def test_demo_project_packs_verifies_and_resumes_as_documented(self) -> None:
        project = TempProject()
        self.addCleanup(project.cleanup)
        for path in (REPO_ROOT / "examples" / "demo-project").rglob("*"):
            if path.is_file():
                project.write(str(path.relative_to(REPO_ROOT / "examples" / "demo-project")), path.read_text())
        with helpers.patched_home(project.home), mock.patch.dict(os.environ, packtools.GIT_ENV):
            project.git_init()
            handoff = {"next_steps": [{"text": "Write the reminder command and its tests.", "status": "fact"}]}
            result = pack.build(project.root, approve=True, handoff=json.dumps(handoff).encode())
            report = verify.verify(project.root)
            _report, output = resume.resume(project.root)
        sections = {s["key"] for s in result.pack["sections"]}
        self.assertTrue({"goals", "constraints", "decisions", "next_steps", "state", "overview"} <= sections)
        self.assertEqual(result.pack["coverage"]["status"], "all_extracted_items_kept")
        self.assertEqual([s["label"] for s in result.pack["sources"] if s["origin"] == "file"],
                         ["README.md", "CLAUDE.md", "docs/decisions/0001-storage.md", "pyproject.toml"])  # fmt: skip
        self.assertEqual((report.exit_code, report.result), (0, "ok"))
        self.assertIn("Write the reminder command and its tests. — S", output or "")


if __name__ == "__main__":
    unittest.main()
