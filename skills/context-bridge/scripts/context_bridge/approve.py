"""approve: record the user's approval of a project's sources. Writes only the consent record.

Approving is a command of its own, separate from ``pack``, on purpose: the skill pre-approves
``pack`` for Claude Code, but not ``approve``. Claude Code therefore asks the user before every
approval, like before ``setup apply``, so the model cannot approve sources on its own initiative.

Without ``--path`` every current source is approved (the files ``scan`` lists as included, git
metadata and the file list); with ``--path`` only the named ones. Excluded files can never be
approved, and files that appear later need a new approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import consent as consent_mod
from . import pack as pack_mod
from . import safepath
from . import scan as scan_mod
from .extract import gitinfo


def _label(source: str) -> str:
    return consent_mod.PSEUDO_LABELS.get(source, source)


def approve(
    root_arg: str | Path,
    paths: tuple[str, ...] = (),
    *,
    user_config_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """Approve the current sources (all, or ``paths``). Returns (newly approved, already approved)."""
    root = safepath.resolve_root(root_arg)
    report = scan_mod.scan(root, user_config_path)
    git = gitinfo.collect(root) if report.vcs == "git" else None
    files, pseudo, _structure = pack_mod.current_sources(report, git)
    record = pack_mod.load_for_approval(root)
    before = set(record.files) | set(record.pseudo)
    when = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pack_mod.grant(record, files, pseudo, approve_all=not paths, paths=paths, when=when)
    wanted = list(paths) if paths else files + pseudo
    if not wanted:
        raise consent_mod.ConsentError("this project has no sources to approve; 'scan' shows why files are excluded")
    consent_mod.save(record)
    return [s for s in wanted if s not in before], [s for s in wanted if s in before]


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "approve",
        help="approve the project's current sources for packing (writes only the approval record outside the project)",
    )
    p.add_argument("--root", default=".", help="project root (default: current directory)")
    p.add_argument(
        "--path",
        action="append",
        default=[],
        metavar="SOURCE",
        help="approve only this source (repeatable): a relative path, '~/' label, 'git' or 'file_list'",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=run_cli)


def run_cli(args: argparse.Namespace) -> int:
    new, known = approve(args.root, tuple(args.path))
    if args.json:
        json.dump({"approved": new, "already_approved": known}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    safe = scan_mod._safe
    lines = [f"Context Bridge approve: {len(new)} source(s) newly approved, {len(known)} already approved."]
    lines += [f"  approved: {safe(_label(s))}" for s in new]
    lines.append("The approval is stored outside the project. Files that appear later need a new approval.")
    lines.append("Next: run 'pack'.")
    print("\n".join(lines))
    return 0
