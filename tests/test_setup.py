"""Self-integration (setup): detection, preview, consent, idempotency, undo, protection, hook.

Everything runs against a fake home directory; no real CLAUDE.md or settings file is touched.
"""

from __future__ import annotations

import json
import shlex
import stat
import unittest
from pathlib import Path

import helpers
from helpers import TempProject, snapshot

from context_bridge import setup
from context_bridge.config import load_config
from context_bridge.setup import BLOCK_RE, SetupError, apply, plan_install, plan_undo

GERMAN_RULES = "# Meine Regeln\n\n- Antworte immer auf Deutsch und nicht zu lang.\n"
ENGLISH_RULES = "# Project rules\n\n- Use the standard library and keep functions small.\n"


class SetupTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.enterContext(helpers.patched_home(self.project.home))
        self.root = self.project.root
        self.claude = self.project.home / ".claude"
        self.claude.mkdir()
        self.global_md = self.claude / "CLAUDE.md"
        self.global_md.write_text(GERMAN_RULES, encoding="utf-8", newline="\n")
        self.project.write("CLAUDE.md", ENGLISH_RULES)

    def cfg(self):  # noqa: ANN201
        return load_config(self.root, include_project=False)

    def install(self, scope: str = "project", kind: str = "instructions", **kwargs: object) -> setup.Plan:
        plan = plan_install(scope, kind, self.root, self.cfg(), script=Path("/opt/cb/scripts/cb.py"), **kwargs)  # type: ignore[arg-type]
        apply(plan, plan.id)
        return plan

    def undo(self, scope: str = "project", kind: str = "instructions") -> setup.Plan:
        plan = plan_undo(scope, kind, self.root, self.cfg())
        apply(plan, plan.id)
        return plan

    def backups(self) -> list[Path]:
        base = self.project.home / ".local" / "state" / "context-bridge" / "setup"
        return sorted(base.glob("*/manifest.json")) if base.is_dir() else []


class DetectionTests(SetupTestCase):
    def test_finds_every_file_claude_code_reads(self) -> None:
        self.project.write("CLAUDE.local.md", "personal\n")
        self.project.write(".claude/CLAUDE.md", "nested\n")
        self.project.write("AGENTS.md", "Context Bridge is mentioned here.\n")
        found = {f["path"]: f for f in setup.detect(self.root, self.cfg())}
        scopes = sorted(f["scope"] for f in found.values())
        self.assertEqual(scopes, ["global", "local", "other tools", "project", "project"])
        self.assertEqual(found["~/.claude/CLAUDE.md"]["has_block"], False)
        agents = next(f for f in found.values() if f["path"].endswith("AGENTS.md"))
        self.assertEqual(agents["similar_lines"], [1])

    @helpers.requires_symlinks
    def test_symlinked_vault_file_is_recognised_and_protected(self) -> None:
        vault = self.project.base / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "CLAUDE.md").symlink_to(self.global_md)
        found = setup.detect(vault, load_config(vault, include_project=False))
        linked = next(f for f in found if f["scope"] == "project")
        self.assertEqual(linked["symlink_to"], "~/.claude/CLAUDE.md")
        self.assertEqual(linked["same_as"], "~/.claude/CLAUDE.md")
        self.assertIn("symlink", linked["protected"])


class InstallTests(SetupTestCase):
    def test_preview_writes_nothing(self) -> None:
        before = snapshot(self.project.base)
        plan = plan_install("project", "instructions", self.root, self.cfg())
        self.assertEqual(plan.action, "install")
        self.assertIn("+<!-- context-bridge:begin v1 -->", plan.diff())
        self.assertEqual(helpers.changed_paths(before, snapshot(self.project.base)), [])

    def test_install_appends_the_block_keeps_everything_else_and_backs_up(self) -> None:
        target = self.root / "CLAUDE.md"
        if helpers.POSIX:
            target.chmod(0o640)
        self.install()
        text = target.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(ENGLISH_RULES))
        self.assertEqual(len(BLOCK_RE.findall(text)), 1)
        self.assertIn("## Context Bridge", text)
        if helpers.POSIX:  # the mode is kept
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        manifest = json.loads(self.backups()[0].read_text(encoding="utf-8"))
        self.assertEqual((manifest["action"], manifest["existed"]), ("install", True))
        backup = self.backups()[0].parent / "before"
        self.assertEqual(backup.read_text(encoding="utf-8"), ENGLISH_RULES)
        if helpers.POSIX:  # the backup is private
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_block_language_follows_the_file_or_the_choice(self) -> None:
        german = plan_install("global", "instructions", self.root, self.cfg())
        self.assertIn("zu Beginn mit dem Skill context-bridge `resume`", german.after.decode())
        self.assertNotIn("ß", german.after.decode())
        english = plan_install("global", "instructions", self.root, self.cfg(), lang="en")
        self.assertIn("run `resume` with the context-bridge skill at the start", english.after.decode())

    def test_block_is_short_and_matches_the_heading_style(self) -> None:
        # GERMAN_RULES has one "#" title; a file structured with several "#" sections gets a "#" section.
        self.global_md.write_text("# Über mich\n- a\n\n# Antworten\n- b\n", encoding="utf-8", newline="\n")
        block = plan_install("global", "instructions", self.root, self.cfg()).after.decode().split("\n\n", 2)[-1]
        self.assertTrue(block.splitlines()[1] == "# Context Bridge", block)
        self.assertEqual(sum(1 for line in block.splitlines() if line.startswith("- ")), 2)
        self.assertLess(len(block) / 4, 80)  # roughly 70 tokens including the markers
        project = plan_install("project", "instructions", self.root, self.cfg()).after.decode()
        self.assertIn("\n## Context Bridge\n", project)

    def test_missing_file_is_created_and_undo_deletes_it(self) -> None:
        local = self.root / "CLAUDE.local.md"
        self.install("local")
        self.assertIn("context-bridge:begin", local.read_text(encoding="utf-8"))
        self.undo("local")
        self.assertFalse(local.exists())

    def test_windows_line_endings_are_kept(self) -> None:
        (self.root / "CLAUDE.md").write_bytes(b"# Rules\r\n\r\n- One.\r\n")
        self.install()
        data = (self.root / "CLAUDE.md").read_bytes()
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))


class IdempotencyTests(SetupTestCase):
    def test_second_install_changes_nothing(self) -> None:
        self.install()
        content = (self.root / "CLAUDE.md").read_bytes()
        again = plan_install("project", "instructions", self.root, self.cfg())
        self.assertEqual(again.action, "none")
        self.assertEqual(apply(again, again.id), {"written": False, "backup": None})
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), content)
        self.assertEqual(len(self.backups()), 1)

    def test_a_different_block_is_updated_in_place(self) -> None:
        self.install(lang="en")
        (self.root / "CLAUDE.md").write_text(
            (self.root / "CLAUDE.md").read_text(encoding="utf-8") + "\n- Added later.\n", encoding="utf-8", newline="\n"
        )
        plan = self.install(lang="de")
        self.assertEqual(plan.action, "update")
        text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(len(BLOCK_RE.findall(text)), 1)
        self.assertIn("zu Beginn", text)
        self.assertTrue(text.rstrip().endswith("- Added later."))

    def test_existing_mentions_block_a_second_entry(self) -> None:
        self.project.write("CLAUDE.md", ENGLISH_RULES + "- Use Context Bridge resume at start.\n")
        plan = plan_install("project", "instructions", self.root, self.cfg())
        self.assertTrue(plan.blockers)
        with self.assertRaises(SetupError):
            apply(plan, plan.id)
        allowed = plan_install("project", "instructions", self.root, self.cfg(), allow_similar=True)
        self.assertEqual(allowed.blockers, [])

    def test_block_in_another_scope_is_not_duplicated(self) -> None:
        self.install("global")
        plan = plan_install("project", "instructions", self.root, self.cfg())
        self.assertTrue(any("already has the block" in b for b in plan.blockers))
        both = plan_install("project", "instructions", self.root, self.cfg(), allow_both=True)
        self.assertEqual(both.blockers, [])
        self.assertTrue(any("already has the block" in w for w in both.warnings))


class ConsentTests(SetupTestCase):
    def test_wrong_or_stale_confirmation_is_refused(self) -> None:
        plan = plan_install("project", "instructions", self.root, self.cfg())
        with self.assertRaises(SetupError):
            apply(plan, "000000000000")
        (self.root / "CLAUDE.md").write_text(
            ENGLISH_RULES + "- Edited after the preview.\n", encoding="utf-8", newline="\n"
        )
        fresh = plan_install("project", "instructions", self.root, self.cfg())
        with self.assertRaises(SetupError):
            apply(fresh, plan.id)  # the id of the old preview no longer matches
        self.assertNotIn("context-bridge:begin", (self.root / "CLAUDE.md").read_text(encoding="utf-8"))


class UndoTests(SetupTestCase):
    def test_undo_restores_the_exact_bytes(self) -> None:
        original = self.global_md.read_bytes()
        self.install("global")
        plan = self.undo("global")
        self.assertEqual(plan.action, "undo-restore")
        self.assertEqual(self.global_md.read_bytes(), original)

    def test_undo_after_an_edit_removes_only_the_block(self) -> None:
        self.install()
        path = self.root / "CLAUDE.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n- My own new rule.\n", encoding="utf-8", newline="\n")
        plan = self.undo()
        self.assertEqual(plan.action, "undo-remove")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("context-bridge", text)
        self.assertIn("- My own new rule.", text)
        self.assertTrue(text.startswith(ENGLISH_RULES))

    def test_nothing_to_undo(self) -> None:
        plan = plan_undo("project", "instructions", self.root, self.cfg())
        self.assertEqual(plan.action, "undo-none")
        self.install()
        self.undo()
        self.assertEqual(plan_undo("project", "instructions", self.root, self.cfg()).action, "undo-none")


class ProtectionTests(SetupTestCase):
    def assertRefused(self, root: Path, scope: str = "project", kind: str = "instructions") -> setup.Plan:
        plan = plan_install(scope, kind, root, load_config(root, include_project=False))
        self.assertTrue(plan.blockers, plan)
        with self.assertRaises(SetupError):
            apply(plan, plan.id)
        return plan

    @helpers.requires_symlinks
    def test_symlinked_target_is_never_written(self) -> None:
        (self.root / "CLAUDE.md").unlink()
        (self.root / "CLAUDE.md").symlink_to(self.global_md)
        plan = self.assertRefused(self.root)
        self.assertIn("symlink", plan.blockers[0])
        self.assertEqual(self.global_md.read_text(encoding="utf-8"), GERMAN_RULES)

    def test_obsidian_vaults_are_never_written(self) -> None:
        vault = self.project.base / "notes-vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "project").mkdir()
        (vault / "project" / "CLAUDE.md").write_text("notes\n", encoding="utf-8", newline="\n")
        plan = self.assertRefused(vault / "project")
        self.assertIn("Obsidian vault", plan.blockers[0])
        self.assertEqual((vault / "project" / "CLAUDE.md").read_text(encoding="utf-8"), "notes\n")

    def test_protected_and_denied_locations(self) -> None:
        cfg = self.project.home / ".config" / "context-bridge" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"[setup]\nprotected_roots = [{helpers.toml_path(self.root)}]\n", encoding="utf-8", newline="\n")
        self.assertIn("protected location", self.assertRefused(self.root).blockers[0])
        cfg.write_text(f"[privacy]\ndeny_roots = [{helpers.toml_path(self.root)}]\n", encoding="utf-8", newline="\n")
        self.assertIn("denied location", self.assertRefused(self.root).blockers[0])

    def test_a_project_cannot_lift_protection(self) -> None:
        cfg = self.project.home / ".config" / "context-bridge" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"[setup]\nprotected_roots = [{helpers.toml_path(self.root)}]\n", encoding="utf-8", newline="\n")
        self.project.write(".context-bridge/config.toml", "[setup]\nprotected_roots = []\n")
        self.assertRefused(self.root)

    def test_oversized_or_undecodable_files_are_left_alone(self) -> None:
        (self.root / "CLAUDE.md").write_bytes(b"\xff\xfe broken")
        self.assertRefused(self.root)
        (self.root / "CLAUDE.md").write_bytes(b"x" * (setup.MAX_FILE_BYTES + 1))
        self.assertRefused(self.root)


class HookTests(SetupTestCase):
    SETTINGS = {
        "permissions": {"deny": ["Read(~/.ssh/**)"]},
        "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "backup.sh"}]}]},
        "theme": "dark",
    }

    def write_settings(self, data: object) -> Path:
        path = self.claude / "settings.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        return path

    def test_hook_keeps_other_settings_is_idempotent_and_undoable(self) -> None:
        path = self.write_settings(self.SETTINGS)
        original = path.read_bytes()
        self.install("global", "hook")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["hooks"]["SessionEnd"], self.SETTINGS["hooks"]["SessionEnd"])
        self.assertEqual((data["permissions"], data["theme"]), (self.SETTINGS["permissions"], "dark"))
        start = data["hooks"]["SessionStart"]
        entry = setup.hook_entry(Path("/opt/cb/scripts/cb.py"))  # exec form on Windows, see HookEntryTests
        self.assertEqual(start, [{"hooks": [entry]}])
        self.assertEqual(entry["timeout"], 10)
        again = plan_install("global", "hook", self.root, self.cfg(), script=Path("/opt/cb/scripts/cb.py"))
        self.assertEqual(again.action, "none")
        self.undo("global", "hook")
        self.assertEqual(path.read_bytes(), original)

    def test_undo_after_other_changes_removes_only_our_hook(self) -> None:
        path = self.write_settings(self.SETTINGS)
        self.install("global", "hook")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"]["SessionStart"].append({"hooks": [{"type": "command", "command": "other.sh"}]})
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        self.assertEqual(self.undo("global", "hook").action, "undo-remove")
        left = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(left["hooks"]["SessionStart"], [{"hooks": [{"type": "command", "command": "other.sh"}]}])
        self.assertEqual(left["hooks"]["SessionEnd"], self.SETTINGS["hooks"]["SessionEnd"])

    def test_invalid_settings_are_never_rewritten(self) -> None:
        path = self.claude / "settings.json"
        path.write_text('{"hooks": [ broken', encoding="utf-8", newline="\n")
        plan = plan_install("global", "hook", self.root, self.cfg())
        self.assertIn("not valid JSON", plan.blockers[0])
        self.assertEqual(path.read_text(encoding="utf-8"), '{"hooks": [ broken')


class HookEntryTests(unittest.TestCase):
    """The SessionStart hook on POSIX systems and on Windows (simulated)."""

    WINDOWS_SCRIPT = r"C:\Users\alice\.claude\skills\context-bridge\scripts\cb.py"

    def test_posix_shell_form_is_unchanged_for_plain_paths_and_quoted_otherwise(self) -> None:
        plain = setup.hook_entry("/opt/cb/scripts/cb.py", windows=False)
        self.assertEqual(plain, {"type": "command", "command": "python3 -I /opt/cb/scripts/cb.py session-start",
                                 "timeout": 10})  # fmt: skip  # installs from 0.1 stay current
        spaced = setup.hook_entry("/Users/alice/My Skills/cb.py", windows=False)["command"]
        self.assertEqual(shlex.split(spaced), ["python3", "-I", "/Users/alice/My Skills/cb.py", "session-start"])

    def test_windows_exec_form_starts_the_running_python_without_a_shell(self) -> None:
        entry = setup.hook_entry(self.WINDOWS_SCRIPT, windows=True, executable=r"C:\Program Files\Python313\python.exe")
        self.assertEqual(entry, {"type": "command", "command": r"C:\Program Files\Python313\python.exe",
                                 "args": ["-I", self.WINDOWS_SCRIPT, "session-start"], "timeout": 10})  # fmt: skip
        self.assertTrue(setup._is_our_hook(entry))
        forward = {
            **entry,
            "args": ["-I", "C:/Users/alice/.claude/skills/context-bridge/scripts/cb.py", "session-start"],
        }
        self.assertTrue(setup._is_our_hook(forward))

    def test_other_hooks_are_not_mistaken_for_ours(self) -> None:
        for hook in ({"type": "command", "command": "python", "args": ["-I", "other.py", "session-start"]},
                     {"type": "command", "command": "python", "args": ["session-start"]},
                     {"type": "command", "command": "python", "args": "cb.py session-start"},
                     {"type": "command", "command": "notify.sh session-start"}, "cb.py session-start"):  # fmt: skip
            with self.subTest(hook=hook):
                self.assertFalse(setup._is_our_hook(hook))

    def test_shell_characters_are_harmless_but_placeholders_block_the_hook(self) -> None:
        for script in (r"C:\Users\alice\$skills\cb.py", r"C:\Users\alice\a%PATH%\cb.py", r"C:\Users\alice\a`b\cb.py"):
            with self.subTest(script=script):  # exec form: no shell expands anything
                self.assertIsNone(
                    setup.hook_command_problem(windows=True, script=script, executable="C:/py/python.exe")
                )
        self.assertIsNone(setup.hook_command_problem(windows=False, script="/opt/$weird/cb.py"))  # quoted by shlex
        for windows, script, executable in ((True, r"C:\x\${CLAUDE_PROJECT_DIR}\cb.py", "C:/py/python.exe"),
                                            (True, r"C:\x\cb.py", r"C:\${HOME}\python.exe"),
                                            (False, "/opt/${CLAUDE_PROJECT_DIR}/cb.py", None)):  # fmt: skip
            with self.subTest(script=script, executable=executable):
                problem = setup.hook_command_problem(windows=windows, script=script, executable=executable)
                self.assertIn("install the hook by hand", problem or "")


class HookAwareBlockTests(SetupTestCase):
    """With the auto-resume hook installed, the CLAUDE.md block drops the redundant resume line."""

    def bullets(self, plan: setup.Plan) -> list[str]:
        added = plan.after.decode()[len(plan.before.decode()) :] if plan.before else plan.after.decode()
        return [line for line in added.splitlines() if line.startswith("- ")]

    def test_resume_line_follows_the_hook(self) -> None:
        full = plan_install("global", "instructions", self.root, self.cfg())
        self.assertEqual(len(self.bullets(full)), 2)
        self.install("global", "hook")
        short = plan_install("global", "instructions", self.root, self.cfg())
        self.assertEqual(
            self.bullets(short),
            ["- Vor dem Ende einer längeren Arbeitssitzung anbieten, den Kontext mit `pack` zu sichern."],
        )
        self.assertTrue(any("resume line is left out" in w for w in short.warnings))
        forced = plan_install("global", "instructions", self.root, self.cfg(), with_resume_line=True)
        self.assertEqual(len(self.bullets(forced)), 2)

    def test_short_block_is_idempotent_and_updates_when_the_hook_goes(self) -> None:
        self.install("global", "hook")
        self.install("global")
        self.assertEqual(plan_install("global", "instructions", self.root, self.cfg()).action, "none")
        self.undo("global", "hook")
        self.assertEqual(plan_install("global", "instructions", self.root, self.cfg()).action, "update")


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        (self.project.home / ".claude").mkdir()
        (self.project.home / ".claude" / "CLAUDE.md").write_text(GERMAN_RULES, encoding="utf-8", newline="\n")
        self.project.write("CLAUDE.md", ENGLISH_RULES)

    def preview_id(self, *args: str) -> str:
        result = self.project.run_cb("setup", "preview", *args, "--json")
        return json.loads(result.stdout)["preview_id"]

    def test_full_cli_flow(self) -> None:
        run = self.project.run_cb
        self.assertIn("~/.claude/CLAUDE.md: no Context Bridge block", run("setup").stdout)
        preview = run("setup", "preview", "--target", "project")
        self.assertEqual(preview.returncode, 1)  # warning: a project CLAUDE.md is shared with the team
        self.assertIn("Nothing was written.", preview.stdout)
        self.assertEqual(run("setup", "apply", "--target", "project").returncode, 64)
        self.assertEqual(run("setup", "apply", "--target", "project", "--confirm", "nope").returncode, 2)
        ok = run("setup", "apply", "--target", "project", "--confirm", self.preview_id("--target", "project"))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("Written: yes", ok.stdout)
        undo_id = json.loads(run("setup", "undo-preview", "--target", "project", "--json").stdout)["preview_id"]
        self.assertEqual(run("setup", "undo", "--target", "project", "--confirm", undo_id).returncode, 0)
        self.assertEqual((self.project.root / "CLAUDE.md").read_text(encoding="utf-8"), ENGLISH_RULES)
        self.assertEqual((self.project.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"), GERMAN_RULES)

    def test_session_start_command_never_fails(self) -> None:
        result = self.project.run_cb("session-start", input_text="not json at all")
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
