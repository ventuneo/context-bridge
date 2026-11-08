"""Safe file access confined to a root directory.

Every read goes through :func:`read_file`, which

* accepts only clean relative paths (no absolute paths, ``..``, ``~``, drive letters, NUL;
  on Windows also no device names, alternate data streams or names ending in a dot or space),
* resolves symlinks and directory junctions and refuses targets outside the root,
* reads regular files only (no FIFOs, devices, sockets or directories),
* enforces a size limit while reading, and
* opens with ``O_NOFOLLOW | O_NONBLOCK`` where the system has them and re-checks the file id
  after opening, so a file swapped for a link or FIFO between the checks is detected (Windows
  has no ``O_NOFOLLOW``; there the re-check after resolving the path does this job).

Limitation: a concurrent local attacker who swaps *intermediate directories* during a
read is out of scope; the threat model is untrusted repository content.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import compat
from .errors import UnsafePathError

BINARY_SNIFF_BYTES = 8192
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

# Reason codes raised as UnsafePathError.reason (stable: they appear in reports).
INVALID_PATH = "invalid_relative_path"
MISSING = "missing"
UNREADABLE = "unreadable"
BROKEN_SYMLINK = "broken_symlink"
SYMLINK_OUTSIDE_ROOT = "symlink_outside_root"
NOT_REGULAR_FILE = "not_regular_file"
TOO_LARGE = "too_large"
CHANGED_DURING_READ = "changed_during_read"


def resolve_root(path: str | os.PathLike[str]) -> Path:
    """Resolve and validate a project root directory."""
    candidate = Path(path).expanduser()
    try:
        root = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError("root_missing", f"project root not found: {candidate}") from exc
    if not root.is_dir():
        raise UnsafePathError("root_not_directory", f"project root is not a directory: {candidate}")
    return root


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def check_relative(rel: str, *, windows: bool = compat.WINDOWS) -> PurePosixPath:
    """Validate a relative POSIX path taken from untrusted input."""
    if not rel or "\x00" in rel or "\\" in rel or rel.startswith("~") or _DRIVE_RE.match(rel):
        raise UnsafePathError(INVALID_PATH, f"invalid relative path: {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise UnsafePathError(INVALID_PATH, f"invalid relative path: {rel!r}")
    if windows:
        for part in pure.parts:
            problem = compat.windows_name_problem(part)
            if problem:
                raise UnsafePathError(INVALID_PATH, f"invalid relative path on Windows: {rel!r} ({part!r} {problem})")
    return pure


@dataclass(frozen=True)
class FileContent:
    rel: str
    data: bytes
    sha256: str
    size: int
    via_symlink: bool


def read_file(root: Path, rel: str, max_bytes: int) -> FileContent:
    """Read ``root/rel`` safely. Raises UnsafePathError with a reason code."""
    check_relative(rel)
    lexical = root / rel
    try:
        os.lstat(lexical)
    except FileNotFoundError as exc:
        raise UnsafePathError(MISSING, f"missing: {rel}") from exc
    except OSError as exc:
        raise UnsafePathError(UNREADABLE, f"unreadable: {rel}") from exc
    is_link = compat.is_link_like(lexical)
    try:
        target = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop on older Pythons
        raise UnsafePathError(BROKEN_SYMLINK if is_link else UNREADABLE, f"cannot resolve: {rel}") from exc
    via_symlink = target != Path(os.path.normpath(lexical))
    if not is_within(target, root):
        raise UnsafePathError(SYMLINK_OUTSIDE_ROOT, f"symlink leaves the project root: {rel}")
    try:
        st = os.stat(target)
    except OSError as exc:
        raise UnsafePathError(UNREADABLE, f"unreadable: {rel}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePathError(NOT_REGULAR_FILE, f"not a regular file: {rel}")
    if st.st_size > max_bytes:
        raise UnsafePathError(TOO_LARGE, f"larger than {max_bytes} bytes: {rel}")
    try:
        fd = os.open(target, os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK | _O_BINARY)
    except OSError as exc:
        raise UnsafePathError(UNREADABLE, f"cannot open: {rel}") from exc
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode) or (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            raise UnsafePathError(CHANGED_DURING_READ, f"file changed during read: {rel}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise UnsafePathError(TOO_LARGE, f"larger than {max_bytes} bytes: {rel}")
    return FileContent(rel, data, hashlib.sha256(data).hexdigest(), len(data), via_symlink)


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


def decode_text(data: bytes) -> tuple[str, bool]:
    """Decode as UTF-8. Returns (text, valid_utf8); invalid bytes become U+FFFD."""
    try:
        text, valid = data.decode("utf-8"), True
    except UnicodeDecodeError:
        text, valid = data.decode("utf-8", errors="replace"), False
    return text.removeprefix("﻿"), valid


def ensure_private_dir(path: Path) -> bool:
    """Create ``path`` (one level) with mode 0700; refuse links and junctions.

    Returns whether the permission bits took effect (always True on Windows, which has none).
    """
    if compat.is_link_like(path):
        raise UnsafePathError("symlinked_store", f"refusing to use a symlinked directory: {path.name}")
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return compat.permissions_enforced(path, 0o700)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write via a temporary file in the same directory and ``os.replace``."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.chmod(tmp, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        compat.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
