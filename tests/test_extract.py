from __future__ import annotations

import unittest

import helpers  # noqa: F401  (puts the package on sys.path)

from context_bridge.extract import markdown, project


def md(text: str, kind: str = "docs") -> list[tuple[str, str, str]]:
    items, _title = markdown.extract(text, "S1", kind, 1)
    return [(i.section, i.status, i.text) for i in items]


class HeadingRoutingTests(unittest.TestCase):
    def test_english_and_german_headings(self) -> None:
        text = (
            "# T\n## Goals\n- Ship it.\n## Ziele\n- Live gehen.\n## Rules\n- No network.\n## Regeln\n- Kein Netz.\n"
            "## Decisions\n- Use TOML.\n## Next steps\n- Write tests.\n## Nächste Schritte\n- Tests schreiben.\n"
            "## Offene Aufgaben\n- Doku.\n## Architecture\n- Two layers.\n"
        )
        self.assertEqual(
            [(s, t) for s, _st, t in md(text)],
            [("goals", "Ship it."), ("goals", "Live gehen."), ("constraints", "No network."),
             ("constraints", "Kein Netz."), ("decisions", "Use TOML."), ("next_steps", "Write tests."),
             ("next_steps", "Tests schreiben."), ("open_tasks", "Doku."), ("structure", "Two layers.")],
        )  # fmt: skip

    def test_subheadings_inherit_their_parent_section(self) -> None:
        self.assertEqual(md("## Rules\n### Python\n- Use the standard library.\n")[0][0], "constraints")

    def test_unrecognised_sections_become_notes_except_agent_rules(self) -> None:
        text = "## Random notes\n- something\n"
        self.assertEqual(md(text), [("unclassified", "fact", "something")])  # kept as data, not dropped (0.3)
        self.assertEqual(md(text, kind="agent_rules"), [("conventions", "fact", "something")])

    def test_readme_overview_skips_badges(self) -> None:
        text = "# App\n\n[![ci](https://x/b.svg)](https://x)\n\nApp does things.\n\n## Usage\nRun it.\n"
        self.assertIn(("overview", "fact", "App does things."), md(text, kind="readme"))


class StatusTests(unittest.TestCase):
    def test_assumptions_and_uncertainty(self) -> None:
        text = (
            "## Annahmen und Unsicheres\n- Die API bleibt stabil.\n- Offen: ob Windows nötig ist.\n"
            "## Goals\n- Maybe support Android.\n- Is offline mode needed?\n- Ship v1.\n"
            "## Notes\nAssumption: users have Python 3.11.\n"
        )
        result = md(text)
        self.assertIn(("open_questions", "assumption", "Die API bleibt stabil."), result)
        self.assertIn(("open_questions", "uncertain", "Offen: ob Windows nötig ist."), result)
        self.assertIn(("goals", "uncertain", "Maybe support Android."), result)
        self.assertIn(("goals", "uncertain", "Is offline mode needed?"), result)
        self.assertIn(("goals", "fact", "Ship v1."), result)
        self.assertIn(("open_questions", "assumption", "Assumption: users have Python 3.11."), result)


class StructureTests(unittest.TestCase):
    def test_key_value_lines_route_directly(self) -> None:
        text = "Ziel: Bis März live.\nStatus: Beta.\nNächster Schritt: Testen.\nDecision: Use SQLite.\n"
        self.assertEqual([s for s, _st, _t in md(text)], ["goals", "state", "next_steps", "decisions"])

    def test_tasks_tables_commands_and_line_numbers(self) -> None:
        text = (
            "## Next\n- [ ] Add CI\n- [x] Done already\n\n| Name | Value |\n|---|---|\n| Port | 8080 |\n"
            "## Getting started\n```sh\n$ make install\n# comment\nmake test\n```\n```python\nprint(1)\n```\n"
        )
        items, _ = markdown.extract(text, "S1", "readme", 1)
        found = [(i.section, i.text, i.lines) for i in items]
        self.assertEqual(
            found,
            [("open_tasks", "Add CI", (2, 2)), ("next_steps", "Port · 8080", (7, 7)),
             ("commands", "make install", (10, 10)), ("commands", "make test", (12, 12))],
        )  # fmt: skip

    def test_multiline_bullets_and_quotes(self) -> None:
        text = "## Rules\n- Never upload data\n  without approval.\n\n> **Status:** beta\n"
        result = md(text)
        self.assertEqual(result[0][2], "Never upload data without approval.")
        self.assertEqual(result[1][0], "state")

    def test_hidden_content_never_becomes_an_item(self) -> None:
        text = "---\ngoal: hidden front matter\n---\n## Goals\n<!--\n- hidden goal\n-->\n- Visible goal.\n"
        self.assertEqual(md(text), [("goals", "fact", "Visible goal.")])

    def test_decision_files_fall_back_to_the_title(self) -> None:
        items, title = markdown.extract("# Use PostgreSQL\n\n## Context\nWe need SQL.\n", "S1", "decisions", 1)
        self.assertEqual(title, "Use PostgreSQL")
        self.assertEqual([(i.section, i.text, i.extractor) for i in items],
                         [("unclassified", "We need SQL.", "markdown.unclassified"),  # the ADR context (0.3)
                          ("decisions", "Use PostgreSQL", "markdown.title")])  # fmt: skip


class ManifestTests(unittest.TestCase):
    def test_pyproject(self) -> None:
        text = '[project]\nname = "demo"\ndescription = "A demo."\nrequires-python = ">=3.11"\ndependencies = ["requests>=2", "rich"]\n'
        items, name = project.manifest_items("pyproject.toml", text, "S1", 4)
        self.assertEqual(name, "demo")
        self.assertEqual(
            [(i.section, i.text) for i in items],
            [("stack", "Python project 'demo'; requires Python >=3.11; dependencies: requests, rich"),
             ("overview", "A demo.")],
        )  # fmt: skip

    def test_package_json_and_makefile(self) -> None:
        items, name = project.manifest_items(
            "package.json",
            '{"name": "web", "scripts": {"dev": "vite", "test": "vitest"}, "dependencies": {"vue": "3"}}',
            "S1",
            4,
        )
        self.assertEqual(name, "web")
        self.assertIn(("commands", "npm run dev: vite"), [(i.section, i.text) for i in items])
        items, _ = project.manifest_items("Makefile", ".PHONY: test\ntest:\n\tpytest\nbuild: deps\nX := 1\n", "S2", 4)
        self.assertEqual([i.text for i in items], ["make test", "make build"])

    def test_unparsable_manifest_is_uncertain(self) -> None:
        items, _ = project.manifest_items("pyproject.toml", "[project\n", "S1", 4)
        self.assertEqual([(i.status, i.extractor) for i in items], [("uncertain", "manifest.unparsed")])


class ProjectExtractorTests(unittest.TestCase):
    def test_structure_summary(self) -> None:
        items = project.structure_items(["README.md", "src/a.py", "src/b.py", "src/c.md", "docs/x.md"], "S9")
        self.assertEqual(
            [i.text for i in items],
            ["Top-level files: README.md", "src/: 3 files (py 2, md 1)", "docs/: 1 file (md 1)"],
        )

    def test_changelog_takes_only_the_newest_section(self) -> None:
        text = "# Changelog\n## 0.2.0\n- Added pack\n- Fixed scan\n## 0.1.0\n- Old entry\n"
        self.assertEqual(
            [i.text for i in project.changelog_items(text, "S1", 4)],
            ["Changelog 0.2.0: Added pack", "Changelog 0.2.0: Fixed scan"],
        )


class GermanHeadingTests(unittest.TestCase):
    def test_singular_and_plural_forms(self) -> None:
        cases = {
            "Entscheidung": "decisions", "Entscheidungen": "decisions", "Begründung": "decisions",
            "Einschränkung": "constraints", "Einschränkungen": "constraints", "Anforderung": "constraints",
            "Prinzip": "constraints", "Grundsatz": "constraints", "Grundsätze": "constraints",
            "Konvention": "conventions", "Abhängigkeit": "stack", "Risiko": "open_questions",
            "Frage": "open_questions", "Unsicherheit": "open_questions", "Annahme": "open_questions",
            "Aufgabe": "open_tasks", "Meilenstein": "open_tasks", "Pendenz": "open_tasks",
        }  # fmt: skip
        for heading, section in cases.items():
            with self.subTest(heading=heading):
                self.assertEqual(markdown.classify_heading(heading)[0], section)


if __name__ == "__main__":
    unittest.main()
