"""Pack origin: which packs Context Bridge itself wrote for this folder on this machine.

The record lives **outside** the project, next to the approvals, in
``$XDG_STATE_HOME/context-bridge/packs/<id>.json`` (default ``~/.local/state``), keyed by the
project's real path. ``pack`` adds the SHA-256 of every pack it writes, and ``verify`` (with it
``resume`` and the SessionStart hook) accepts a pack only when its exact bytes are listed there.

A pack that arrives with the project - committed with ``git add -f``, copied from another folder
or another machine, or written by hand - is therefore never shown as verified: a repository can
no more ship its own pack than its own approval. Packs written before this record existed, and
packs of a moved project, have to be packed again.

A missing, unreadable or corrupt record trusts nothing (fail closed).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from . import compat, safepath, store
from .consent import root_key
from .errors import ContextBridgeError

ORIGIN_FORMAT = "context-bridge.packs"
ORIGIN_VERSION = "1.0"
MAX_RECORD_BYTES = 1024 * 1024


class OriginError(ContextBridgeError):
    """The pack record cannot be read or written."""


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return compat.state_home(env) / "context-bridge" / "packs"


def record_path(root: Path, env: Mapping[str, str] | None = None) -> Path:
    return state_dir(env) / f"{root_key(root)}.json"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(root: Path) -> dict[str, str]:
    """pack id -> SHA-256 of the pack JSON, for the packs written for this folder. {} if none."""
    path = record_path(root)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_RECORD_BYTES + 1)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise OriginError(f"cannot read the pack record: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OriginError("the pack record is corrupt") from exc
    if not isinstance(data, dict):
        raise OriginError("the pack record is corrupt")
    packs = data.get("packs")
    if (
        len(raw) > MAX_RECORD_BYTES
        or data.get("format") != ORIGIN_FORMAT
        or not isinstance(packs, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in packs.items())
    ):
        raise OriginError("the pack record is corrupt")
    return dict(packs)


def is_local(root: Path, pack_id: str, raw: bytes) -> tuple[bool, str]:
    """Whether ``raw`` is exactly a pack that ``pack`` wrote for ``root`` here, and why not."""
    try:
        packs = load(root)
    except OriginError as exc:
        return False, str(exc)
    expected = packs.get(pack_id)
    if expected is None:
        return False, "this folder has no record of the pack"
    if expected != digest(raw):
        return False, "the pack differs from the one that was written here"
    return True, ""


def add(root: Path, pack_id: str, raw: bytes) -> None:
    """Record a pack before it is written. Entries of packs that are gone from the store are dropped."""
    try:
        packs = load(root)
    except OriginError:
        packs = {}  # a corrupt record trusted nothing; it is replaced by one that lists this pack
    packs_dir = root / store.STORE_DIR / store.PACKS_DIR
    kept = {pid: h for pid, h in packs.items() if os.path.lexists(packs_dir / f"{pid}.json")}
    kept[pack_id] = digest(raw)
    data = {
        "format": ORIGIN_FORMAT,
        "version": ORIGIN_VERSION,
        "root": str(root),
        "packs": dict(sorted(kept.items())),
    }
    path = record_path(root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safepath.ensure_private_dir(path.parent)
    safepath.atomic_write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
