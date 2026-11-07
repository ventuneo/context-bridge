"""Local pack store inside the project: ``<root>/.context-bridge/``.

* directories 0700, files 0600, every write atomic (temporary file + ``os.replace``)
* the store ignores itself in git (``.context-bridge/.gitignore`` contains ``*``), so the
  project's own ``.gitignore`` is never touched
* symlinked store directories are refused; files are replaced, never written through
* only files matching the pack naming scheme are ever deleted (retention)
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from . import safepath
from .errors import UnsafePathError

STORE_DIR = ".context-bridge"
PACKS_DIR = "packs"
DEFAULT_KEEP = 10
GITIGNORE = b"# Created by Context Bridge. Context packs are local and must never be committed.\n*\n"
PACK_NAME_RE = re.compile(r"^(\d{8}T\d{6}Z-[0-9a-f]{6})\.(json|md)$")


def _private_dir(path: Path) -> None:
    if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise UnsafePathError("unsafe_store", f"refusing to use {path.name}: not a plain directory")
    safepath.ensure_private_dir(path)


def prepare(root: Path) -> Path:
    store = root / STORE_DIR
    _private_dir(store)
    gitignore = store / ".gitignore"
    if not os.path.lexists(gitignore):
        safepath.atomic_write(gitignore, GITIGNORE)
    _private_dir(store / PACKS_DIR)
    return store


def prune(packs: Path, keep: int) -> int:
    """Delete all but the newest ``keep`` packs. Returns the number of packs removed."""
    ids: set[str] = set()
    for name in os.listdir(packs):
        match = PACK_NAME_RE.match(name)
        if match and stat.S_ISREG(os.lstat(packs / name).st_mode):
            ids.add(match.group(1))
    old = sorted(ids)[: max(0, len(ids) - keep)]
    for pack_id in old:
        for ext in ("json", "md"):
            path = packs / f"{pack_id}.{ext}"
            if os.path.lexists(path) and stat.S_ISREG(os.lstat(path).st_mode):
                os.unlink(path)
    return len(old)


def write_pack(root: Path, pack_id: str, json_bytes: bytes, md_bytes: bytes, keep: int = DEFAULT_KEEP) -> dict:
    if not PACK_NAME_RE.match(f"{pack_id}.json"):
        raise ValueError(f"invalid pack id: {pack_id}")
    store = prepare(root)
    packs = store / PACKS_DIR
    safepath.atomic_write(packs / f"{pack_id}.json", json_bytes)
    safepath.atomic_write(packs / f"{pack_id}.md", md_bytes)
    safepath.atomic_write(store / "latest.json", json_bytes)
    safepath.atomic_write(store / "latest.md", md_bytes)
    removed = prune(packs, max(1, keep))
    rel = f"{STORE_DIR}/{PACKS_DIR}/{pack_id}"
    return {
        "json": f"{rel}.json",
        "markdown": f"{rel}.md",
        "latest_json": f"{STORE_DIR}/latest.json",
        "latest_markdown": f"{STORE_DIR}/latest.md",
        "pruned": removed,
    }
