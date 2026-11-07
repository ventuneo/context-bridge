"""Path policy: hard deny rules, noise directories, allowlist, deny roots and globbing.

Relative paths are POSIX strings such as ``docs/setup.md``. Matching is
case-insensitive because macOS and Windows file systems usually are, so
``.ENV`` is treated like ``.env``.

The hard rules in this module are not configurable. Configuration can only add
exclusions (see ``config.py``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Exclusion reason codes (stable: they appear in JSON reports).
SECRET_FILE = "secret_file"
SECRET_DIR = "secret_dir"
NOISE_DIR = "noise_dir"
PERSONAL_FILE = "personal_file"
EXCLUDED_BY_CONFIG = "excluded_by_config"
NOT_IN_ALLOWLIST = "not_in_allowlist"
DENY_ROOT = "deny_root"

# File names that are never read, whatever any configuration says.
SECRET_FILE_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.env", ".envrc",
    "*.pem", "*.key", "*.p8", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "*.ppk", "*.ovpn",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd", ".pgpass",
    "credentials", "credentials.*", "secrets.*", "*.secret", "*.secrets",
    "*.tfstate", "*.tfstate.*", "*.mobileprovision", "service-account*.json",
)  # fmt: skip
# Directory names whose whole subtree is never read.
SECRET_DIR_NAMES: frozenset[str] = frozenset(
    {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", "secrets", ".secrets", ".password-store"}
)
# Generated or vendored content: skipped to save budget, not for secrecy.
NOISE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", ".context-bridge", "node_modules", ".venv", "venv", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", "dist", "build", "target",
        ".next", ".nuxt", ".cache", "DerivedData", ".gradle", ".terraform", ".idea", ".vscode",
    }
)  # fmt: skip
# Personal, usually git-ignored files that must not end up in a shared pack.
PERSONAL_FILE_PATTERNS: tuple[str, ...] = ("*.local.md", "*.local.json", "*.local.toml")

# Default allowlist: (glob, kind). The first matching pattern decides the kind.
DEFAULT_INCLUDE: tuple[tuple[str, str], ...] = (
    ("README", "readme"),
    ("README.*", "readme"),
    ("CLAUDE.md", "agent_rules"),
    ("AGENTS.md", "agent_rules"),
    ("GEMINI.md", "agent_rules"),
    (".cursorrules", "agent_rules"),
    (".cursor/rules/*.mdc", "agent_rules"),
    (".github/copilot-instructions.md", "agent_rules"),
    ("**/CLAUDE.md", "agent_rules"),
    ("**/AGENTS.md", "agent_rules"),
    ("CHANGELOG*", "changelog"),
    ("HISTORY*", "changelog"),
    ("NEWS*", "changelog"),
    ("pyproject.toml", "manifest"),
    ("setup.cfg", "manifest"),
    ("requirements*.txt", "manifest"),
    ("package.json", "manifest"),
    ("Cargo.toml", "manifest"),
    ("go.mod", "manifest"),
    ("Package.swift", "manifest"),
    ("project.yml", "manifest"),
    ("Gemfile", "manifest"),
    ("composer.json", "manifest"),
    ("pom.xml", "manifest"),
    ("build.gradle", "manifest"),
    ("build.gradle.kts", "manifest"),
    ("deno.json", "manifest"),
    ("pubspec.yaml", "manifest"),
    ("mix.exs", "manifest"),
    ("Makefile", "manifest"),
    ("justfile", "manifest"),
    ("Taskfile.yml", "manifest"),
    ("**/adr/**/*.md", "decisions"),
    ("**/decisions/**/*.md", "decisions"),
    ("*.md", "docs"),
    ("docs/**/*.md", "docs"),
    ("docs/**/*.rst", "docs"),
    ("docs/**/*.txt", "docs"),
    ("doc/**/*.md", "docs"),
    ("**/README.md", "docs"),
)

# Reading order when the total byte budget runs out: most valuable kinds first.
KIND_PRIORITY: dict[str, int] = {
    "readme": 0, "agent_rules": 1, "decisions": 2, "manifest": 3, "changelog": 4, "docs": 5, "custom": 6,
}  # fmt: skip


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a glob into a regex. ``*`` and ``?`` stay within one path segment,
    ``**/`` matches zero or more directories and a bare ``**`` matches anything."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE | re.DOTALL)


def globmatch(pattern: str, path: str) -> bool:
    return _compile(pattern).match(path) is not None


def _matches_any(patterns: Iterable[str], name: str) -> bool:
    return any(globmatch(p, name) for p in patterns)


def dir_exclusion(name: str) -> str | None:
    """Reason to skip a whole directory with this name, or None."""
    folded = name.casefold()
    if folded in _SECRET_DIRS_FOLDED:
        return SECRET_DIR
    if folded in _NOISE_DIRS_FOLDED:
        return NOISE_DIR
    return None


_SECRET_DIRS_FOLDED = frozenset(n.casefold() for n in SECRET_DIR_NAMES)
_NOISE_DIRS_FOLDED = frozenset(n.casefold() for n in NOISE_DIR_NAMES)


@dataclass(frozen=True)
class PathDecision:
    included: bool
    reason: str | None = None  # exclusion reason when not included
    kind: str | None = None  # allowlist kind when included


def classify(
    rel: str,
    include: Sequence[tuple[str, str]] = DEFAULT_INCLUDE,
    exclude: Sequence[str] = (),
) -> PathDecision:
    """Decide whether a relative file path may be read, by name alone."""
    segments = rel.split("/")
    for directory in segments[:-1]:
        reason = dir_exclusion(directory)
        if reason:
            return PathDecision(False, reason)
    name = segments[-1]
    if _matches_any(SECRET_FILE_PATTERNS, name):
        return PathDecision(False, SECRET_FILE)
    if _matches_any(PERSONAL_FILE_PATTERNS, name):
        return PathDecision(False, PERSONAL_FILE)
    if _matches_any(exclude, rel):
        return PathDecision(False, EXCLUDED_BY_CONFIG)
    for pattern, kind in include:
        if globmatch(pattern, rel):
            return PathDecision(True, kind=kind)
    return PathDecision(False, NOT_IN_ALLOWLIST)


class DenyRoots:
    """Directories that must never be read, compared by device and inode.

    Inode comparison is immune to symlinks, ``..`` tricks and case variations on
    case-insensitive file systems. Deny roots that do not exist are ignored.
    """

    def __init__(self, paths: Iterable[Path]) -> None:
        self._ids: set[tuple[int, int]] = set()
        for path in paths:
            try:
                st = os.stat(path)
            except OSError:
                continue
            self._ids.add((st.st_dev, st.st_ino))

    def __bool__(self) -> bool:
        return bool(self._ids)

    def is_deny_root(self, path: Path) -> bool:
        try:
            st = os.stat(path)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) in self._ids

    def blocks(self, path: Path) -> bool:
        """True if ``path`` or any of its ancestors (lexical or resolved) is a deny root."""
        if not self._ids:
            return False
        candidates = {Path(os.path.abspath(path)), Path(os.path.realpath(path))}
        for base in candidates:
            for candidate in (base, *base.parents):
                if self.is_deny_root(candidate):
                    return True
        return False
