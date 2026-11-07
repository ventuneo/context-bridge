"""Hardened, read-only git access.

* Fixed subcommands as argument lists, never a shell, always a timeout.
* ``--no-pager``, ``--no-optional-locks`` and ``-c`` overrides that disable fsmonitor,
  the untracked cache and signature verification.
* Variables that redirect git to another repository (``GIT_DIR`` and friends) are removed.
* Before any other command, the repository's own configuration is inspected. If it
  contains a key that can make git start a program (filters, diff drivers, fsmonitor,
  pager, gpg, includes, ...), git is not used at all and callers fall back to a plain
  directory walk. A cloned repository cannot ship such keys, but a downloaded archive
  that contains a ``.git`` directory can.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 15

_BASE_ARGS = (
    "--no-pager",
    "--no-optional-locks",
    "-c", "core.fsmonitor=false",
    "-c", "core.untrackedCache=false",
    "-c", "log.showSignature=false",
    "-c", "core.quotePath=false",
)  # fmt: skip
_REDIRECT_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR", "GIT_SSH", "GIT_SSH_COMMAND",
)  # fmt: skip
_DANGEROUS_KEYS = re.compile(
    r"^(?:core\.(?:fsmonitor|pager|editor|sshcommand|gitproxy|askpass)|sequence\.editor|pager\..+|"
    r"filter\..+\.(?:clean|smudge|process)|diff\..+\.(?:textconv|command)|diff\.external|merge\..+\.driver|"
    r"gpg\.program|gpg\..+\.program|include\.path|includeif\..+\.path)$"
)
_FALSE_VALUES = {"false", "no", "off", "0", ""}

# Reason codes (stable: they appear in reports).
NOT_INSTALLED = "git_not_installed"
NOT_A_REPO = "not_a_repo"
UNTRUSTED_CONFIG = "git_skipped_untrusted_config"
GIT_FAILED = "git_error"


class GitError(Exception):
    pass


@dataclass(frozen=True)
class GitStatus:
    usable: bool
    is_repo: bool
    reason: str | None = None
    untrusted_keys: tuple[str, ...] = ()


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECT_VARS}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", PAGER="cat")
    return env


def run_git(root: Path, args: Sequence[str], timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Run one git command in ``root`` and return stdout. Raises GitError."""
    git = shutil.which("git")
    if git is None:
        raise GitError(NOT_INSTALLED)
    try:
        proc = subprocess.run(
            [git, *_BASE_ARGS, *args],
            cwd=root,
            env=_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {args[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(f"git {args[0]} exited with {proc.returncode}")
    return proc.stdout


def _dangerous(key: str, value: str) -> bool:
    key = key.casefold()
    if not _DANGEROUS_KEYS.match(key):
        return False
    return not (key == "core.fsmonitor" and value.strip().casefold() in _FALSE_VALUES)


def untrusted_keys(config_listing: bytes) -> tuple[str, ...]:
    """Parse ``git config --list -z`` output and return keys that can run programs."""
    found: set[str] = set()
    for entry in config_listing.split(b"\0"):
        if not entry:
            continue
        key, _, value = entry.decode("utf-8", errors="replace").partition("\n")
        if _dangerous(key, value):
            found.add(key.casefold())
    return tuple(sorted(found))


def inspect(root: Path) -> GitStatus:
    """Decide whether git may be used for ``root``."""
    if shutil.which("git") is None:
        return GitStatus(False, False, NOT_INSTALLED)
    try:
        inside = run_git(root, ["rev-parse", "--is-inside-work-tree"]).strip()
    except GitError:
        return GitStatus(False, False, NOT_A_REPO)
    if inside != b"true":
        return GitStatus(False, False, NOT_A_REPO)
    try:
        listing = run_git(root, ["config", "--local", "--includes", "--list", "-z"])
    except GitError:
        return GitStatus(False, True, GIT_FAILED)
    keys = untrusted_keys(listing)
    if keys:
        return GitStatus(False, True, UNTRUSTED_CONFIG, keys)
    return GitStatus(True, True)


def list_files(root: Path) -> list[str]:
    """Tracked and untracked-but-not-ignored files below ``root``, relative to it."""
    out = run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    seen: dict[str, None] = {}
    for raw in out.split(b"\0"):
        if raw:
            seen.setdefault(raw.decode("utf-8", errors="surrogateescape"), None)
    return list(seen)
