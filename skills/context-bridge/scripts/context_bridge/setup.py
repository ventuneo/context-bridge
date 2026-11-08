"""setup: integrate Context Bridge into Claude Code.

Two things can be installed, each on its own and each only after a preview:

* **instructions**: a short, marked block in a CLAUDE.md file (global, project or local)
* **hook** (optional): a SessionStart hook in a settings.json that loads a short, verified
  digest of the project's context pack at startup and resume (see ``autoresume``).

Rules that make this safe:

* ``preview`` writes nothing. It prints a unified diff and a preview id.
* ``apply`` re-plans from the current files and writes only if the plan has exactly the
  confirmed preview id, so a file that changed in between, or a different change, is refused.
* Before every write a backup and a manifest are stored in
  ``$XDG_STATE_HOME/context-bridge/setup/``; ``undo`` restores the backup if the file is
  unchanged since, otherwise it removes only Context Bridge's own block or hook entry.
* Installation is idempotent: the block lives between markers and is replaced in place;
  other mentions of Context Bridge and an existing block in another scope are reported.
* Protected, never written: symlinked targets (they would change another file), anything
  inside an Obsidian vault, deny roots and ``[setup] protected_roots`` from the user config,
  undecodable files and settings files that are not valid JSON.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from . import autoresume, compat, safepath
from .config import Config, load_config
from .errors import EXIT_ERROR, EXIT_OK, EXIT_WARNINGS, ContextBridgeError, UsageError

SCOPES = ("global", "project", "local")
KINDS = ("instructions", "hook")
BLOCK_VERSION = 1
MARK_BEGIN = f"<!-- context-bridge:begin v{BLOCK_VERSION} -->"
MARK_END = "<!-- context-bridge:end -->"
BLOCK_RE = re.compile(r"<!-- context-bridge:begin v\d+ -->.*?<!-- context-bridge:end -->(?:\r?\n)?", re.DOTALL)
SIMILAR_RE = re.compile(r"context[ _-]?bridge", re.IGNORECASE)
MAX_FILE_BYTES = 256 * 1024
HOOK_ARG = "session-start"
HOOK_SUFFIX = " " + HOOK_ARG
HOOK_TIMEOUT = 10  # seconds; verify takes well under one second

# Kept short on purpose: it is read in every session. The skill itself enforces consent, the
# untrusted-data rules and the coverage wording whenever pack or resume run, so they are not repeated.
BLOCK_TEXT = {
    "en": [
        "- In projects with `.context-bridge/`, run `resume` with the context-bridge skill at the start and "
        "summarise the state briefly.",
        "- Before ending a longer working session, offer to save the context with `pack`.",
    ],
    "de": [
        "- In Projekten mit `.context-bridge/` zu Beginn mit dem Skill context-bridge `resume` ausführen und den "
        "Stand kurz zusammenfassen.",
        "- Vor dem Ende einer längeren Arbeitssitzung anbieten, den Kontext mit `pack` zu sichern.",
    ],
}
_GERMAN = re.compile(r"\b(und|nicht|der|die|das|ist|mit|für|ich|wenn|immer|nie)\b", re.IGNORECASE)
_ENGLISH = re.compile(r"\b(and|not|the|is|with|for|when|always|never|you)\b", re.IGNORECASE)


class SetupError(ContextBridgeError):
    """A setup step was refused; nothing was written."""


# ---------------------------------------------------------------------------
# Paths


def _home() -> Path:
    return compat.home()  # on Windows the user profile, which is where Claude Code keeps .claude


def display(path: Path) -> str:
    try:
        return "~/" + path.relative_to(_home()).as_posix()
    except ValueError:
        return str(path)


def target_path(scope: str, kind: str, root: Path) -> Path:
    claude_dir = _home() / ".claude"
    if kind == "hook":
        return {
            "global": claude_dir / "settings.json",
            "project": root / ".claude" / "settings.json",
            "local": root / ".claude" / "settings.local.json",
        }[scope]
    if scope == "global":
        return claude_dir / "CLAUDE.md"
    if scope == "local":
        return root / "CLAUDE.local.md"
    nested = root / ".claude" / "CLAUDE.md"
    return nested if nested.exists() and not (root / "CLAUDE.md").exists() else root / "CLAUDE.md"


def _real(path: Path) -> Path:
    """Real path of a file, or of its nearest existing parent for files that do not exist yet."""
    probe = path
    while not os.path.lexists(probe) and probe.parent != probe:
        probe = probe.parent
    return Path(os.path.realpath(probe)) / path.relative_to(probe) if probe != path else Path(os.path.realpath(path))


def _vault_of(path: Path) -> Path | None:
    for directory in (path, *path.parents):
        if (directory / ".obsidian").is_dir():
            return directory
    return None


def protection(path: Path, cfg: Config) -> str | None:
    """Why setup must not write ``path`` (None: writing is allowed)."""
    if path.is_symlink():
        return f"is a symlink to {display(Path(os.path.realpath(path)))}; writing it would change that file"
    real = _real(path)
    vault = _vault_of(real.parent)
    if vault is not None:
        return f"lies inside the Obsidian vault {display(vault)}; setup never writes into notes"
    if cfg.deny().blocks(real if real.exists() else real.parent):
        return "lies inside a denied location (privacy.deny_roots)"
    for protected in cfg.protected_roots:
        if safepath.is_within(real, Path(os.path.realpath(protected))):
            return f"lies inside a protected location ({display(protected)})"
    return None


# ---------------------------------------------------------------------------
# Detection


def detect(root: Path, cfg: Config) -> list[dict[str, Any]]:
    """Every CLAUDE.md-like file Claude Code would read for ``root``, with its state."""
    candidates: list[tuple[str, Path]] = [("global", _home() / ".claude" / "CLAUDE.md")]
    candidates += [
        ("project", root / "CLAUDE.md"),
        ("project", root / ".claude" / "CLAUDE.md"),
        ("local", root / "CLAUDE.local.md"),
        ("other tools", root / "AGENTS.md"),
    ]
    for parent in root.parents:  # Claude Code also reads CLAUDE.md files in parent directories
        if parent == _home() or parent == parent.parent:
            break
        candidates.append(("parent", parent / "CLAUDE.md"))
    seen: dict[Path, str] = {}
    found = []
    for scope, path in candidates:
        if not os.path.lexists(path):
            continue
        real = Path(os.path.realpath(path))
        entry: dict[str, Any] = {
            "scope": scope,
            "path": display(path),
            "symlink_to": None,
            "same_as": None,
            "has_block": False,
            "similar_lines": [],
            "protected": protection(path, cfg),
        }
        if path.is_symlink():
            entry["symlink_to"] = display(real)
        if real in seen:
            entry["same_as"] = seen[real]
        seen.setdefault(real, display(path))
        try:
            text = real.read_bytes()[: MAX_FILE_BYTES + 1].decode("utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        entry["has_block"] = bool(BLOCK_RE.search(text))
        outside = BLOCK_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        entry["similar_lines"] = [n for n, line in enumerate(outside.splitlines(), 1) if SIMILAR_RE.search(line)]
        found.append(entry)
    return found


# ---------------------------------------------------------------------------
# Plans


@dataclass
class Plan:
    scope: str
    kind: str
    path: Path
    action: str  # install | update | none | undo-restore | undo-remove | undo-none
    before: bytes | None
    after: bytes | None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    manifest: Path | None = None

    @property
    def id(self) -> str:
        def digest(data: bytes | None) -> str:
            return hashlib.sha256(data).hexdigest() if data is not None else "missing"

        material = json.dumps(
            [
                str(_real(self.path)),
                self.kind,
                self.action,
                digest(self.before),
                digest(self.after),
                str(self.manifest or ""),
            ]
        )
        return hashlib.sha256(material.encode()).hexdigest()[:12]

    @property
    def changes(self) -> bool:
        return self.action not in ("none", "undo-none")

    def diff(self) -> str:
        old = (self.before or b"").decode("utf-8", "replace").splitlines(keepends=True)
        new = (self.after or b"").decode("utf-8", "replace").splitlines(keepends=True)
        name = display(self.path)
        lines = difflib.unified_diff(
            old,
            new,
            fromfile=f"a/{name}" if self.before is not None else "/dev/null",
            tofile=f"b/{name}" if self.after is not None else "/dev/null",
        )
        return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def _read(path: Path) -> bytes | None:
    if not os.path.lexists(path):
        return None
    if not path.is_file():
        raise SetupError(f"{display(path)} is not a regular file")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise SetupError(f"{display(path)} is larger than 256 KiB; setup does not change it")
    return data


def detect_language(text: str) -> str:
    return "de" if len(_GERMAN.findall(text)) > len(_ENGLISH.findall(text)) else "en"


def heading_level(text: str) -> int:
    """Use the file's own section level: files that structure with several '#' headings get '#'."""
    return 1 if len(re.findall(r"^# \S", text, re.MULTILINE)) >= 2 else 2


def render_block(lang: str, newline: str = "\n", level: int = 2, with_resume_line: bool = True) -> str:
    heading = "#" * level + " Context Bridge"
    lines = BLOCK_TEXT[lang] if with_resume_line else BLOCK_TEXT[lang][1:]
    return newline.join([MARK_BEGIN, heading, *lines, MARK_END]) + newline


def hook_installed(root: Path) -> bool:
    """Is the auto-resume hook configured in any settings file that applies to ``root``?"""
    for scope in SCOPES:
        path = target_path(scope, "hook", root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("hooks", {}).get("SessionStart", [])
            if any(_is_our_hook(h) for e in entries if isinstance(e, dict) for h in e.get("hooks", [])):
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def hook_entry(script: Path | str, *, windows: bool = compat.WINDOWS, executable: str | None = None) -> dict[str, Any]:
    """The SessionStart hook for settings.json.

    macOS, Linux and WSL: shell form, ``python3 -I <script> session-start``. The script path is
    quoted only if it needs it, so hooks installed by 0.1 stay current.

    Windows: exec form, ``command`` plus ``args`` (Claude Code 2.1.139 or later). Claude Code runs a
    shell-form hook in Git Bash, or in PowerShell when Git Bash is not installed, and no quoting
    of a program path works in both; exec form starts the program directly, without a shell.
    ``command`` is the Python that runs setup, because ``python3`` is usually missing on Windows.
    """
    if windows:
        python, path = str(PureWindowsPath(executable or sys.executable)), str(PureWindowsPath(script))
        return {"type": "command", "command": python, "args": ["-I", path, HOOK_ARG], "timeout": HOOK_TIMEOUT}
    return {
        "type": "command",
        "command": f"python3 -I {shlex.quote(str(script))}{HOOK_SUFFIX}",
        "timeout": HOOK_TIMEOUT,
    }


def hook_command_problem(
    *, windows: bool = compat.WINDOWS, script: Path | str, executable: str | None = None
) -> str | None:
    """Why the hook cannot be written safely on this system, or None.

    Claude Code replaces path placeholders such as ``${CLAUDE_PROJECT_DIR}`` in ``command`` and in
    ``args`` before it starts the hook, so a path that contains ``${`` could be changed.
    """
    paths = [("the skill", str(script))] + ([("Python", executable or sys.executable)] if windows else [])
    for label, value in paths:
        if "${" in value:
            return (f"the path of {label} contains '${{', which Claude Code treats as a placeholder; install the "
                    "hook by hand (see docs/setup.md)")  # fmt: skip
    return None


def _is_our_hook(hook: Any) -> bool:
    """A Context Bridge SessionStart hook, in shell form or in exec form (Windows)."""
    if not isinstance(hook, dict):
        return False
    command, args = hook.get("command", ""), hook.get("args")
    if isinstance(args, list):
        return (len(args) >= 2 and args[-1] == HOOK_ARG and isinstance(args[-2], str)
                and PureWindowsPath(args[-2]).name == "cb.py")  # fmt: skip
    return isinstance(command, str) and command.endswith(HOOK_SUFFIX) and "cb.py" in command


def _indent_of(text: str) -> int:
    match = re.search(r"^( +)\S", text, re.MULTILINE)
    return len(match.group(1)) if match else 2


def _base_plan(scope: str, kind: str, root: Path, cfg: Config, action: str) -> tuple[Plan, bytes | None]:
    path = target_path(scope, kind, root)
    plan = Plan(scope, kind, path, action, None, None)
    reason = protection(path, cfg)
    if reason:
        plan.blockers.append(f"{display(path)} {reason}")
        return plan, None
    try:
        plan.before = _read(path)
    except SetupError as exc:
        plan.blockers.append(str(exc))
    return plan, plan.before


def _parse_settings(plan: Plan, raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        plan.blockers.append(f"{display(plan.path)} is not valid JSON; setup will not rewrite it")
        return None
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(hooks, dict) or not isinstance(hooks.get("SessionStart", []), list):
        plan.blockers.append(f"{display(plan.path)} has an unexpected structure; setup will not rewrite it")
        return None
    return data


def _dump_settings(data: dict[str, Any], original: bytes | None, plan: Plan) -> bytes:
    indent = _indent_of(original.decode("utf-8")) if original else 2
    text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    if original is not None:
        normalised = json.dumps(json.loads(original.decode("utf-8")), indent=indent, ensure_ascii=False) + "\n"
        if normalised != original.decode("utf-8"):
            plan.warnings.append("the settings file will also be re-formatted (see the diff)")
    return text.encode("utf-8")


def plan_install(
    scope: str,
    kind: str,
    root: Path,
    cfg: Config,
    *,
    lang: str | None = None,
    script: Path | None = None,
    allow_similar: bool = False,
    allow_both: bool = False,
    with_resume_line: bool | None = None,
) -> Plan:
    plan, before = _base_plan(scope, kind, root, cfg, "install")
    if plan.blockers:
        return plan
    if kind == "hook":
        data = _parse_settings(plan, before)
        if data is None:
            return plan
        script_path = script or Path(sys.argv[0]).absolute()
        problem = hook_command_problem(script=script_path)
        if problem:
            plan.blockers.append(problem)
            return plan
        desired = {"hooks": [hook_entry(script_path)]}
        entries = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        ours = [e for e in entries if isinstance(e, dict) and any(_is_our_hook(h) for h in e.get("hooks", []))]
        if ours == [desired]:
            plan.action, plan.after = "none", before
            return plan
        kept = []
        for entry in entries:  # replace an older Context Bridge hook in place, keep everything else
            if entry in ours:
                others = [h for h in entry.get("hooks", []) if not _is_our_hook(h)]
                if others:
                    kept.append({**entry, "hooks": others})
            else:
                kept.append(entry)
        data["hooks"]["SessionStart"] = [*kept, desired]
        plan.action = "update" if ours else "install"
        plan.after = _dump_settings(data, before, plan)
        return plan

    try:
        text = (before or b"").decode("utf-8")
    except UnicodeDecodeError:
        plan.blockers.append(f"{display(plan.path)} is not UTF-8 text")
        return plan
    newline = "\r\n" if "\r\n" in text else "\n"
    hook = hook_installed(root)
    include_resume = (not hook) if with_resume_line is None else with_resume_line
    block = render_block(lang or detect_language(text), newline, heading_level(text), include_resume)
    if hook and not include_resume:
        plan.warnings.append(
            "the auto-resume hook is installed, so the resume line is left out (the context would load twice)"
        )
    existing = BLOCK_RE.search(text)
    if existing:
        current = existing.group(0) if existing.group(0).endswith(("\n", "\r\n")) else existing.group(0) + newline
        if current == block:
            plan.action, plan.after = "none", before
            return plan
        plan.action = "update"
        plan.after = (text[: existing.start()] + block + text[existing.end() :]).encode("utf-8")
        return plan
    similar = [n for n, line in enumerate(text.splitlines(), 1) if SIMILAR_RE.search(line)]
    if similar and not allow_similar:
        plan.blockers.append(
            f"{display(plan.path)} already mentions Context Bridge outside a marked block (lines "
            f"{', '.join(map(str, similar[:10]))}); review them, or confirm with --allow-similar"
        )
    for other in SCOPES:
        if other == scope:
            continue
        other_path = target_path(other, "instructions", root)
        try:
            same_file = os.path.realpath(other_path) == os.path.realpath(plan.path)
            has_block = other_path.is_file() and bool(BLOCK_RE.search(other_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
        if has_block and not same_file:
            message = f"the {other} file {display(other_path)} already has the block"
            if allow_both:
                plan.warnings.append(message)
            else:
                plan.blockers.append(message + "; installing it here too would duplicate it (use --allow-both)")
    separator = "" if not text else (newline if text.endswith(("\n", "\r\n")) else newline * 2)
    plan.after = (text + separator + block).encode("utf-8")
    if scope == "project":
        plan.warnings.append("a project CLAUDE.md is usually versioned: the block applies to everyone on the team")
    return plan


def _state_dir() -> Path:
    return compat.state_home() / "context-bridge" / "setup"


def _manifests(path: Path, kind: str) -> list[tuple[Path, dict[str, Any]]]:
    root = _state_dir()
    if not root.is_dir():
        return []
    found = []
    for manifest in sorted(root.glob("*/manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("real_path") == str(_real(path)) and data.get("kind") == kind and not data.get("undone_at"):
            found.append((manifest, data))
    return found


def plan_undo(scope: str, kind: str, root: Path, cfg: Config) -> Plan:
    plan, current = _base_plan(scope, kind, root, cfg, "undo-none")
    if plan.blockers:
        return plan
    plan.after = current
    history = [(m, d) for m, d in _manifests(plan.path, kind) if d.get("action") in ("install", "update")]
    current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
    if history:
        manifest, data = history[-1]
        if current_sha == data.get("after_sha256"):
            backup = manifest.parent / "before"
            plan.action, plan.manifest = "undo-restore", manifest
            plan.after = backup.read_bytes() if data.get("existed") and backup.is_file() else None
            return plan
        plan.warnings.append("the file changed since setup wrote it; only Context Bridge's own part is removed")
    if current is None:
        return plan
    if kind == "hook":
        data = _parse_settings(plan, current)
        if data is None:
            return plan
        entries = data.get("hooks", {}).get("SessionStart", [])
        kept = []
        for entry in entries:
            hooks = [h for h in entry.get("hooks", []) if not _is_our_hook(h)] if isinstance(entry, dict) else None
            if hooks is None or hooks:
                kept.append(entry if hooks is None else {**entry, "hooks": hooks})
        if kept != entries:
            data["hooks"]["SessionStart"] = kept
            if not kept:
                del data["hooks"]["SessionStart"]
            if not data["hooks"]:
                del data["hooks"]
            plan.action, plan.after = "undo-remove", _dump_settings(data, current, plan)
        return plan
    text = current.decode("utf-8", "replace")
    if BLOCK_RE.search(text):
        cleaned = BLOCK_RE.sub("", text)
        cleaned = re.sub(r"(\r?\n){3,}$", lambda m: m.group(1), cleaned)
        plan.action, plan.after = "undo-remove", cleaned.encode("utf-8")
    return plan


# ---------------------------------------------------------------------------
# Applying


def apply(plan: Plan, confirm: str) -> dict[str, Any]:
    if plan.blockers:
        raise SetupError("refused: " + "; ".join(plan.blockers))
    if confirm != plan.id:
        raise SetupError(
            "the confirmation does not match the current preview (the file or the planned change "
            "differs); run the preview again and confirm its id"
        )
    if not plan.changes:
        return {"written": False, "backup": None}
    when = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = _state_dir() / f"{when}-{plan.id}"
    backup_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safepath.ensure_private_dir(backup_dir.parent)
    safepath.ensure_private_dir(backup_dir)
    mode = stat.S_IMODE(os.stat(plan.path).st_mode) if plan.before is not None else 0o644
    if plan.before is not None:
        safepath.atomic_write(backup_dir / "before", plan.before)
    manifest = {
        "format": "context-bridge.setup",
        "action": plan.action,
        "kind": plan.kind,
        "scope": plan.scope,
        "path": display(plan.path),
        "real_path": str(_real(plan.path)),
        "existed": plan.before is not None,
        "before_sha256": hashlib.sha256(plan.before).hexdigest() if plan.before is not None else None,
        "after_sha256": hashlib.sha256(plan.after).hexdigest() if plan.after is not None else None,
        "created_at": when,
    }
    safepath.atomic_write(backup_dir / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    if plan.after is None:
        if plan.path.is_symlink() or not plan.path.is_file():
            raise SetupError(f"refusing to delete {display(plan.path)}: not a regular file")
        plan.path.unlink()
    else:
        plan.path.parent.mkdir(parents=True, exist_ok=True)
        safepath.atomic_write(plan.path, plan.after, mode)
    if plan.manifest is not None:
        undone = json.loads(plan.manifest.read_text(encoding="utf-8"))
        undone["undone_at"] = when
        safepath.atomic_write(plan.manifest, (json.dumps(undone, indent=2) + "\n").encode())
    return {"written": True, "backup": display(backup_dir)}


# ---------------------------------------------------------------------------
# CLI


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("setup", help="integrate Context Bridge into CLAUDE.md or a SessionStart hook (preview first)")
    p.add_argument(
        "action", nargs="?", default="status", choices=("status", "preview", "apply", "undo-preview", "undo")
    )
    p.add_argument("--target", choices=SCOPES, help="global (~/.claude), project (shared) or local (personal)")
    p.add_argument("--hook", action="store_true", help="the optional SessionStart hook instead of the CLAUDE.md block")
    p.add_argument("--lang", choices=tuple(BLOCK_TEXT), help="language of the block (default: like the target file)")
    p.add_argument("--confirm", metavar="ID", help="preview id to apply (required for apply and undo)")
    p.add_argument("--allow-similar", action="store_true", help="install although Context Bridge is mentioned already")
    p.add_argument("--allow-both", action="store_true", help="install although another scope has the block")
    p.add_argument(
        "--with-resume-line", action="store_true", help="keep the resume line although the hook is installed"
    )
    p.add_argument("--root", default=".", help="project root (default: current directory)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=run_cli)
    s = sub.add_parser("session-start", help=argparse.SUPPRESS)
    s.set_defaults(handler=run_session_start)


def run_session_start(args: argparse.Namespace) -> int:
    try:
        stdin = sys.stdin.buffer.read(1024 * 1024) if not sys.stdin.isatty() else b""
    except (OSError, ValueError):
        stdin = b""
    text = autoresume.digest(stdin)
    if text:
        sys.stdout.write(text)
    return EXIT_OK


def _plan(args: argparse.Namespace, root: Path, cfg: Config) -> Plan:
    if args.target is None:
        raise UsageError("--target global|project|local is required for this action")
    kind = "hook" if args.hook else "instructions"
    if args.action in ("preview", "apply"):
        return plan_install(
            args.target,
            kind,
            root,
            cfg,
            lang=args.lang,
            allow_similar=args.allow_similar,
            allow_both=args.allow_both,
            with_resume_line=True if args.with_resume_line else None,
        )
    return plan_undo(args.target, kind, root, cfg)


def _print_plan(plan: Plan, args: argparse.Namespace, applied: dict[str, Any] | None = None) -> None:
    if args.json:
        data = {
            "scope": plan.scope,
            "kind": plan.kind,
            "target": display(plan.path),
            "action": plan.action,
            "preview_id": plan.id,
            "diff": plan.diff(),
            "warnings": plan.warnings,
            "blockers": plan.blockers,
            "applied": applied,
        }
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    words = {
        "install": "install the Context Bridge part",
        "update": "update the Context Bridge part in place",
        "none": "nothing to do: already installed exactly like this",
        "undo-restore": "restore the backup",
        "undo-remove": "remove only the Context Bridge part",
        "undo-none": "nothing to undo",
    }
    print(f"Context Bridge setup · {args.action} · {plan.scope} {plan.kind}")
    print(f"Target: {display(plan.path)}")
    print(f"Action: {words[plan.action]}")
    for warning in plan.warnings:
        print(f"Warning: {warning}")
    for blocker in plan.blockers:
        print(f"Refused: {blocker}")
    if applied is not None:
        print(f"Written: {'yes, backup in ' + applied['backup'] if applied['written'] else 'no change needed'}")
        if applied["written"]:
            hook = " --hook" if plan.kind == "hook" else ""
            print(f"Undo: setup undo-preview --target {plan.scope}{hook}, then setup undo with that id")
        return
    if plan.blockers:
        print("Nothing was written.")
        return
    if plan.changes:
        print(plan.diff(), end="")
        verb = "apply" if args.action == "preview" else "undo"
        hook = " --hook" if plan.kind == "hook" else ""
        print(f"Preview id: {plan.id}")
        print(f"To write exactly this change: setup {verb} --target {plan.scope}{hook} --confirm {plan.id}")
    print("Nothing was written.")


def run_cli(args: argparse.Namespace) -> int:
    root = safepath.resolve_root(args.root)
    cfg = load_config(root, include_project=False)  # the project cannot loosen what setup may touch
    if args.action == "status":
        found = detect(root, cfg)
        if args.json:
            json.dump({"files": found}, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return EXIT_OK
        print("Context Bridge setup · status (nothing is written)")
        if not found:
            print("No CLAUDE.md files found.")
        for f in found:
            notes = []
            if f["symlink_to"]:
                notes.append(f"symlink to {f['symlink_to']}")
            if f["same_as"]:
                notes.append(f"same file as {f['same_as']}")
            notes.append("has the Context Bridge block" if f["has_block"] else "no Context Bridge block")
            if f["similar_lines"]:
                notes.append(f"mentions Context Bridge on lines {', '.join(map(str, f['similar_lines'][:5]))}")
            if f["protected"]:
                notes.append(f"protected: {f['protected']}")
            print(f"  {f['scope']:<11} {f['path']}: {'; '.join(notes)}")
        print(
            "Targets: global = ~/.claude/CLAUDE.md (all projects), project = CLAUDE.md (shared with the team), "
            "local = CLAUDE.local.md (personal)."
        )
        print("Next: setup preview --target <global|project|local> [--hook]")
        return EXIT_OK
    plan = _plan(args, root, cfg)
    if args.action in ("apply", "undo"):
        if not args.confirm:
            raise UsageError(f"{args.action} needs --confirm <preview id>; run the preview first")
        applied = apply(plan, args.confirm)
        _print_plan(plan, args, applied)
        return EXIT_OK
    _print_plan(plan, args)
    if plan.blockers:
        return EXIT_ERROR
    return EXIT_WARNINGS if plan.warnings else EXIT_OK
