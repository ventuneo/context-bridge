"""Consent: which sources the user has approved for packing.

The record lives **outside** the project, in
``$XDG_STATE_HOME/context-bridge/consent/<id>.json`` (default ``~/.local/state``),
keyed by the project's real path. A repository therefore cannot ship its own
approval, and a moved project has to be approved again.

Sources are approved by identity (relative path, ``~/`` label of an external note, or
one of the pseudo sources ``git`` and ``file_list``), not by content: an approved file
may change, but a new file is never packed until it is approved.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import compat, safepath
from .errors import ContextBridgeError

CONSENT_FORMAT = "context-bridge.consent"
CONSENT_VERSION = "1.0"
MAX_CONSENT_BYTES = 1024 * 1024
PSEUDO_GIT = "git"
PSEUDO_FILE_LIST = "file_list"
PSEUDO_LABELS = {
    PSEUDO_GIT: "git metadata (branch, HEAD, changed file names, recent commit subjects)",
    PSEUDO_FILE_LIST: "file list (names and counts only, no contents)",
}


class ConsentError(ContextBridgeError):
    """Consent is missing, invalid or the approval request is wrong."""


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return compat.state_home(env) / "context-bridge" / "consent"


def consent_path(root: Path, env: Mapping[str, str] | None = None) -> Path:
    # The same folder under two spellings (case on Windows) must find the same approval.
    key = hashlib.sha256(compat.path_key(root).encode("utf-8", "surrogateescape")).hexdigest()[:32]
    return state_dir(env) / f"{key}.json"


@dataclass
class Consent:
    path: Path
    root: Path
    files: dict[str, str] = field(default_factory=dict)  # label -> approved_at
    pseudo: dict[str, str] = field(default_factory=dict)
    exists: bool = False

    def pending(self, files: Iterable[str], pseudo: Iterable[str]) -> tuple[list[str], list[str]]:
        return [f for f in files if f not in self.files], [p for p in pseudo if p not in self.pseudo]

    def approve(self, files: Iterable[str], pseudo: Iterable[str], when: str) -> None:
        for label in files:
            self.files.setdefault(label, when)
        for label in pseudo:
            self.pseudo.setdefault(label, when)

    def to_json(self) -> bytes:
        data = {
            "format": CONSENT_FORMAT,
            "version": CONSENT_VERSION,
            "root": str(self.root),
            "files": dict(sorted(self.files.items())),
            "pseudo": dict(sorted(self.pseudo.items())),
        }
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _string_map(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ConsentError(f"consent record is corrupt ('{name}'); approve again with --approve")
    return dict(value)


def load(root: Path) -> Consent:
    path = consent_path(root)
    record = Consent(path=path, root=root)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_CONSENT_BYTES + 1)
    except FileNotFoundError:
        return record
    except OSError as exc:
        raise ConsentError(f"cannot read the consent record: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsentError("consent record is corrupt; approve again with --approve") from exc
    if len(raw) > MAX_CONSENT_BYTES or not isinstance(data, dict) or data.get("format") != CONSENT_FORMAT:
        raise ConsentError("consent record is corrupt; approve again with --approve")
    record.files = _string_map(data.get("files", {}), "files")
    record.pseudo = _string_map(data.get("pseudo", {}), "pseudo")
    record.exists = True
    return record


def save(record: Consent) -> None:
    directory = record.path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    safepath.ensure_private_dir(directory)
    safepath.atomic_write(record.path, record.to_json())
