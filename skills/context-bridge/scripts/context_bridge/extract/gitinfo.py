"""Read-only git metadata for the pack: branch, HEAD, changed file names, recent subjects.

Uses the hardened runner in ``gitrun``; nothing is collected when git may not be used.
Commit subjects are untrusted text and are sanitised like every other item.
"""

from __future__ import annotations

import re
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


# --- helpers for verify/resume -------------------------------------------------------
# References come from packs, which are untrusted: only plain hex object names are ever
# passed to git, so a crafted value cannot be read as an option such as --output=...
GIT_REF_RE = re.compile(r"^[0-9a-f]{4,40}$")


def _safe_ref(ref: str) -> str:
    if not GIT_REF_RE.match(ref):
        raise ValueError("invalid git reference")
    return ref


def ref_exists(root: Path, ref: str) -> bool:
    try:
        gitrun.run_git(root, ["cat-file", "-e", f"{_safe_ref(ref)}^{{commit}}"])
    except gitrun.GitError:
        return False
    return True


def is_ancestor(root: Path, ref: str) -> bool:
    """True if ``ref`` is part of the current history (not rewritten away by amend or rebase)."""
    try:
        gitrun.run_git(root, ["merge-base", "--is-ancestor", _safe_ref(ref), "HEAD"])
    except gitrun.GitError:
        return False
    return True


def commits_since(root: Path, ref: str, limit: int = 10) -> tuple[int, list[tuple[str, str]]]:
    """Number of commits after ``ref`` and the newest ``limit`` of them as (sha, subject)."""
    span = f"{_safe_ref(ref)}..HEAD"
    count = int(gitrun.run_git(root, ["rev-list", "--count", span]).strip() or 0)
    log = gitrun.run_git(root, ["log", f"-n{limit}", "--no-show-signature", "--format=%h%x00%s%x1e", span])
    commits = []
    for record in filter(None, (r.strip("\n") for r in log.decode("utf-8", "replace").split("\x1e"))):
        sha, _, subject = record.partition("\x00")
        commits.append((sha, subject))
    return count, commits


def commit_info(root: Path, sha: str) -> tuple[str, str] | None:
    """(date, subject) of a commit, or None if it does not exist."""
    try:
        out = gitrun.run_git(root, ["show", "-s", "--no-show-signature", "--format=%cs%x00%s", _safe_ref(sha)])
    except gitrun.GitError:
        return None
    date, _, subject = out.decode("utf-8", "replace").strip("\n").partition("\x00")
    return date, subject
