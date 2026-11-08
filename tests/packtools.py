"""Shared fixtures for verify/resume tests: a synthetic project and pack tampering."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import helpers  # noqa: F401  (puts the package on sys.path)
from helpers import TempProject

from context_bridge import pack as pack_mod
from context_bridge.render import render_markdown

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
STORE = ".context-bridge"


def make_project(p: TempProject) -> None:
    p.write(
        "README.md",
        "# Field Notes\n\nField Notes captures inspections offline.\n\n## Goals\n- Offline capture without network.\n"
        "- Export reports as PDF.\n\n## Next steps\n- Build the sync queue.\n- Add signature capture.\n",
    )
    p.write("CLAUDE.md", "# Rules\n- Keep functions small.\n- Never upload data without approval.\n")
    p.write("docs/decisions/0001-sqlite.md", "# Use SQLite\n\nDecision: SQLite as local store.\n")
    p.write("docs/old.md", "## Open questions\n- Is Excel export needed?\n")
    p.write("pyproject.toml", '[project]\nname = "field-notes"\nrequires-python = ">=3.11"\n')
    p.write("src/app.py", "print(1)\n")


def load_latest(root: Path) -> dict[str, Any]:
    return json.loads((root / STORE / "latest.json").read_text(encoding="utf-8"))


def recompute(pack: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Recompute every hash like an attacker who knows the format would."""
    pack = dict(pack)
    pack.pop("integrity", None)
    fp = pack_mod.fingerprint(pack)
    pack["pack_id"] = pack["created_at"].replace("-", "").replace(":", "") + "-" + fp[:6]
    md = render_markdown(pack)
    pack["integrity"] = {
        "algorithm": "sha256",
        "fingerprint": fp,
        "content_hash": pack_mod.content_hash(pack),
        "markdown_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(),
    }
    return pack, md


def tamper(root: Path, mutate: Callable[[dict[str, Any]], None], rehash: bool = True) -> dict[str, Any]:
    pack = load_latest(root)
    mutate(pack)
    md = (root / STORE / "latest.md").read_text(encoding="utf-8")
    if rehash:
        pack, md = recompute(pack)
    (root / STORE / "latest.json").write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (root / STORE / "latest.md").write_text(md, encoding="utf-8", newline="\n")
    return pack


def item(pack: dict[str, Any], text_start: str) -> dict[str, Any]:
    return next(i for s in pack["sections"] for i in s["items"] if i["text"].startswith(text_start))
