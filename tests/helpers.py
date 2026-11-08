"""Shared test helpers.

* puts the skill's ``scripts`` directory on ``sys.path``
* builds throw-away projects in temporary directories
* isolates HOME / XDG_CONFIG_HOME so tests never read the developer's real files
* installs an audit hook that fails any test which opens a file inside the real
  home directory (outside this repository and the Python installation)
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "context-bridge" / "scripts"
CB_SCRIPT = SCRIPTS_DIR / "cb.py"
PRIVACY_CHECK = REPO_ROOT / "tools" / "privacy_check.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_REAL_HOME = Path(os.path.expanduser("~")).resolve()
_CANDIDATES = {
    str(REPO_ROOT),
    str(Path(sys.prefix).resolve()),
    str(Path(sys.base_prefix).resolve()),
    str(Path(tempfile.gettempdir()).resolve()),
    *(str(Path(p).resolve()) for p in sys.path if p),
}
# Never allow the home directory itself or one of its ancestors (e.g. a cwd of "~").
_ALLOWED_UNDER_HOME = tuple(
    a for a in _CANDIDATES if not (str(_REAL_HOME) == a or str(_REAL_HOME).startswith(a.rstrip(os.sep) + os.sep))
)


class HomeAccessError(PermissionError):
    """Raised when a test touches the real home directory."""


def _home_guard(event: str, args: tuple) -> None:
    if event != "open" or not args:
        return
    target = args[0]
    if isinstance(target, int) or target is None:
        return
    try:
        path = os.path.realpath(os.fsdecode(target))
    except (TypeError, ValueError):
        return
    path, home = os.path.normcase(path), os.path.normcase(str(_REAL_HOME))  # Windows paths ignore case
    if (path == home or path.startswith(home + os.sep)) and not any(
        path == os.path.normcase(allowed) or path.startswith(os.path.normcase(allowed) + os.sep)
        for allowed in _ALLOWED_UNDER_HOME
    ):
        raise HomeAccessError(f"test opened a file in the real home directory: {path}")


if not getattr(sys, "_context_bridge_home_guard", False):
    sys.addaudithook(_home_guard)
    sys._context_bridge_home_guard = True  # type: ignore[attr-defined]


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(tmp, os.path.join(tmp, "probe"), target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


# CB_TEST_NO_SYMLINKS=1 simulates Windows without Developer Mode, where creating a symlink fails.
_NO_SYMLINKS = os.environ.get("CB_TEST_NO_SYMLINKS") == "1"
SYMLINKS = not _NO_SYMLINKS and _symlinks_supported()
requires_symlinks = unittest.skipUnless(
    SYMLINKS, "creating symbolic links needs Developer Mode or admin rights on Windows"
)
POSIX = os.name == "posix"
requires_posix_permissions = unittest.skipUnless(POSIX, "Windows has no POSIX permission bits")


def remove_tree(path: Path) -> None:
    """``rm -rf`` that also removes read-only files: git makes its object files read-only, and
    Windows refuses to delete those. Anything that still cannot be removed is left behind."""

    def writable_and_retry(function, target, *_exc):  # type: ignore[no-untyped-def]
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable_and_retry)
    else:
        shutil.rmtree(path, onerror=writable_and_retry)


def make_tempdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="cb-test-")).resolve()


# Newer git versions start "git maintenance run --auto --detach" after a commit. That background
# process can change .git while a test compares snapshots, and hold files that a cleanup removes.
GIT_NO_BACKGROUND_WORK = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "gc.auto",
    "GIT_CONFIG_VALUE_1": "0",
}


def isolated_env(home: Path) -> dict[str, str]:
    """Environment for subprocesses: fake HOME, no user git config, no CB config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CONTEXT_BRIDGE_", "PYTHON"))}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),  # Windows takes the home folder from here, not from HOME
        APPDATA=str(home / "AppData" / "Roaming"),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_STATE_HOME=str(home / ".local" / "state"),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
        **GIT_NO_BACKGROUND_WORK,
    )
    return env


@contextlib.contextmanager
def patched_home(home: Path) -> Iterator[Path]:
    """Point HOME (USERPROFILE on Windows) and the config and state folders at ``home``."""
    keys = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_STATE_HOME",
            "CONTEXT_BRIDGE_CONFIG")  # fmt: skip
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ["APPDATA"] = str(home / "AppData" / "Roaming")
    os.environ["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    os.environ["XDG_CONFIG_HOME"] = str(home / ".config")
    os.environ["XDG_STATE_HOME"] = str(home / ".local" / "state")
    os.environ.pop("CONTEXT_BRIDGE_CONFIG", None)
    try:
        yield home
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TempProject:
    """A throw-away project directory with a sibling fake home directory."""

    def __init__(self) -> None:
        self.base = make_tempdir()
        self.root = self.base / "project"
        self.home = self.base / "home"
        self.root.mkdir()
        self.home.mkdir()

    def __enter__(self) -> TempProject:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        remove_tree(self.base)

    def write(self, rel: str, content: str | bytes = "", mode: int | None = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
        if mode is not None:
            path.chmod(mode)
        return path

    def symlink(self, rel: str, target: str | Path) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if _NO_SYMLINKS:
            raise OSError("simulated: creating symlinks needs Developer Mode on Windows")
        path.symlink_to(target, target_is_directory=Path(target).is_dir())  # Windows needs to know
        return path

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=isolated_env(self.home),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )

    def git_init(self, commit: bool = True) -> None:
        self.git("init", "-q", "-b", "main")
        if commit:
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "initial", "--allow-empty")

    def run_cb(self, *args: str, cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(CB_SCRIPT), *args],
            cwd=cwd or self.root,
            env=isolated_env(self.home),
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )


def toml_path(path: Path | str) -> str:
    """A path as a TOML literal string: no escapes, so Windows backslashes stay as they are."""
    text = str(path)
    if "'" in text or "\n" in text:
        raise ValueError(f"cannot write {text!r} as a TOML literal string")
    return f"'{text}'"


def hook_argv(hook: dict) -> list[str]:
    """What Claude Code starts for a command hook: exec form directly, shell form through ``sh -c``."""
    if "args" in hook:
        return [hook["command"], *hook["args"]]
    return ["sh", "-c", hook["command"]]


def changed_paths(before: dict[str, tuple[int, int, bytes]], after: dict[str, tuple[int, int, bytes]]) -> list[str]:
    """Paths added, removed or changed between two snapshots: a readable failure instead of a huge diff."""
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def snapshot(root: Path) -> dict[str, tuple[int, int, bytes]]:
    """Map of every path below ``root`` to (mode, size, content-or-link-target)."""
    result: dict[str, tuple[int, int, bytes]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            st = path.lstat()
            if path.is_symlink():
                data = os.readlink(path).encode()
            elif path.is_file():
                data = path.read_bytes()
            else:
                data = b""
            result[str(path.relative_to(root))] = (st.st_mode, st.st_size, data)
    return result
