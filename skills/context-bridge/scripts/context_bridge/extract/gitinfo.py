"""Read-only git metadata for the pack: branch, HEAD, changed file names, recent subjects.

Uses the hardened runner in ``gitrun``; nothing is collected when git may not be used.
Commit subjects are untrusted text and are sanitised like every other item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import gitrun, policy
from ..model import FACT, Item

MAX_COMMITS = 5
MAX_CHANGED_NAMES = 12
_HIDDEN_REASONS = {policy.SECRET_FILE, policy.SECRET_DIR, policy.PERSONAL_FILE}


@dataclass
class GitInfo:
    branch: str
    head: str | None
    changed: list[str] = field(default_factory=list)
    changed_total: int = 0
    commits: list[tuple[str, str, str]] = field(default_factory=list)  # (sha, date, subject)


def _changed_files(root: Path) -> list[str]:
    prefix = gitrun.run_git(root, ["rev-parse", "--show-prefix"]).decode("utf-8", "replace").strip()
    out = gitrun.run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=normal", "--no-renames", "."])
    names: list[str] = []
    for entry in out.split(b"\0"):
        if len(entry) > 3:
            path = entry[3:].decode("utf-8", "replace")  # porcelain paths are relative to the repo root
            names.append(path[len(prefix) :] if prefix and path.startswith(prefix) else path)
    return names


def collect(root: Path) -> GitInfo | None:
    if not gitrun.inspect(root).usable:
        return None
    try:
        branch = gitrun.run_git(root, ["branch", "--show-current"]).decode("utf-8", "replace").strip() or "(detached)"
        changed = [n for n in _changed_files(root) if policy.classify(n).reason not in _HIDDEN_REASONS]
    except gitrun.GitError:
        return None
    info = GitInfo(branch=branch, head=None, changed=sorted(changed)[:MAX_CHANGED_NAMES], changed_total=len(changed))
    try:
        info.head = gitrun.run_git(root, ["rev-parse", "--short", "HEAD"]).decode().strip()
        log = gitrun.run_git(
            root, ["log", f"-n{MAX_COMMITS}", "--no-show-signature", "--format=%h%x00%cs%x00%s%x1e"]
        ).decode("utf-8", "replace")
        for record in filter(None, (r.strip("\n") for r in log.split("\x1e"))):
            sha, date, subject = (record.split("\x00") + ["", ""])[:3]
            info.commits.append((sha, date, subject))
    except gitrun.GitError:
        pass  # repository without commits
    return info


def git_items(info: GitInfo, source_id: str) -> list[Item]:
    head = info.head or "no commits yet"
    if info.changed_total:
        more = f" and {info.changed_total - len(info.changed)} more" if info.changed_total > len(info.changed) else ""
        changes = f"{info.changed_total} uncommitted changes: {', '.join(info.changed)}{more}"
    else:
        changes = "no uncommitted changes"
    items = [
        Item(
            "state",
            f"git: branch {info.branch} at {head}, {changes}",
            FACT,
            source_id,
            "git.status",
            order=0,
            origin_rank=1,
        )
    ]
    for index, (sha, date, subject) in enumerate(info.commits, start=1):
        items.append(
            Item(
                "state",
                f"Recent commit {sha} ({date}): {subject}",
                FACT,
                source_id,
                "git.log",
                order=index,
                origin_rank=1,
            )
        )
    return items
