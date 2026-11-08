"""Operating-system differences in one place: native Windows, WSL and other POSIX systems.

* **Home folder.** On Windows it is the user profile (``USERPROFILE``), the folder Claude Code
  uses. Git Bash may set ``HOME`` to a POSIX-style path that native programs cannot open.
* **Data and configuration.** ``XDG_STATE_HOME`` and ``XDG_CONFIG_HOME`` win everywhere. Without
  them, Windows uses ``%LOCALAPPDATA%`` and ``%APPDATA%``, other systems ``~/.local/state`` and
  ``~/.config``.
* **Unsafe names on Windows.** Device names (``CON``, ``NUL``, ``COM1`` …, also with an
  extension), ``:`` (alternate data streams), other characters Windows forbids, and names that
  end in a dot or a space are refused. Windows would open a device, a hidden stream or a
  different file instead.
* **Links.** Symbolic links and directory junctions count as links. Other reparse points, such
  as OneDrive placeholders, are ordinary files.
* **Permissions.** Windows has no POSIX permission bits; private files rely on the access rules
  of the user's folders. On POSIX systems :func:`permissions_enforced` tells whether ``chmod``
  took effect: a Windows drive mounted in WSL, for example, ignores it.
* **Replacing files.** On Windows another process (a search indexer, a virus scanner) can hold a
  file for a moment, so :func:`replace` retries briefly.
* **Output.** On Windows, pipes use the ANSI code page unless told otherwise, and ``python -I``
  ignores ``PYTHONUTF8``; :func:`utf8_stdio` makes stdout and stderr UTF-8.

Every function that depends on the platform takes ``windows=`` so that tests can exercise the
Windows behaviour on any system.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import stat
import sys
import time
from collections.abc import Mapping
from pathlib import Path

WINDOWS = os.name == "nt"
_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)$", re.IGNORECASE)
_FORBIDDEN = frozenset('<>:"|?*') | frozenset(chr(code) for code in range(32))
# IO_REPARSE_TAG_SYMLINK and IO_REPARSE_TAG_MOUNT_POINT (directory junctions); see winnt.h.
LINK_REPARSE_TAGS = frozenset({0xA000000C, 0xA0000003})


def _environ(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def home(env: Mapping[str, str] | None = None, *, windows: bool = WINDOWS) -> Path:
    """The user's home folder, the one Claude Code uses for ``.claude``."""
    env = _environ(env)
    if windows:
        profile = env.get("USERPROFILE")
        return Path(profile) if profile else Path(os.path.expanduser("~"))
    return Path(env.get("HOME") or os.path.expanduser("~"))


def state_home(env: Mapping[str, str] | None = None, *, windows: bool = WINDOWS) -> Path:
    """Base folder for state: approvals and setup backups."""
    env = _environ(env)
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]).expanduser()
    if windows and env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"])
    return home(env, windows=windows) / ".local" / "state"


def config_home(env: Mapping[str, str] | None = None, *, windows: bool = WINDOWS) -> Path:
    """Base folder for the user configuration."""
    env = _environ(env)
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]).expanduser()
    if windows and env.get("APPDATA"):
        return Path(env["APPDATA"])
    return home(env, windows=windows) / ".config"


def windows_name_problem(part: str) -> str | None:
    """Why one path component is unsafe on Windows, or None if it is fine."""
    if any(ch in _FORBIDDEN for ch in part):
        return "contains a character Windows does not allow in file names, or names an alternate data stream"
    if part not in (".", "..") and part.endswith((".", " ")):
        return "ends with a dot or a space, which Windows removes, so another file would be opened"
    if _DEVICE.match(part.split(".", 1)[0].rstrip(" ")):
        return "is a Windows device name"
    return None


def is_link_like(path: str | os.PathLike[str]) -> bool:
    """A symbolic link, or a directory junction on Windows. Missing paths are not links."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in LINK_REPARSE_TAGS


def path_key(path: str | os.PathLike[str], *, windows: bool = WINDOWS) -> str:
    """A string that is equal for two spellings of the same path (case-insensitive on Windows)."""
    return (ntpath if windows else posixpath).normcase(os.fspath(path))


def permissions_enforced(path: str | os.PathLike[str], expected: int, *, windows: bool = WINDOWS) -> bool:
    """POSIX: did the permission bits take effect? Windows has none, so this is always True there."""
    if windows:
        return True
    try:
        return stat.S_IMODE(os.stat(path).st_mode) == expected
    except OSError:
        return False


def is_wsl() -> bool:
    """Running in the Windows Subsystem for Linux."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        with open("/proc/sys/kernel/osrelease", encoding="ascii", errors="replace") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def replace(src: str | os.PathLike[str], dst: str | os.PathLike[str], *, windows: bool = WINDOWS,
            attempts: int = 6) -> None:  # fmt: skip
    """``os.replace``; on Windows, retry for a moment while another process holds the target."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not windows or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def utf8_stdio() -> None:
    """Make stdout and stderr write UTF-8 (pack text contains characters such as ⚠ and →)."""
    for stream, errors in ((sys.stdout, "replace"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None or (stream.encoding or "").lower().replace("-", "") == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except (ValueError, OSError):
            pass
