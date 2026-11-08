"""Session handoff: what the assistant learned in the conversation, validated as data.

Format (JSON object, every field optional)::

    {
      "goal": "...",
      "status": {"text": "...", "status": "fact"},
      "done": ["..."],
      "constraints": [{"text": "...", "status": "fact"}],
      "decisions": [{"text": "...", "reason": "...", "status": "fact"}],
      "next_steps": [...], "open_questions": [...],
      "files_touched": ["relative/path.py"],
      "author": "assistant"
    }

Entries are a string or an object with ``text`` and ``status`` (``fact``,
``assumption`` or ``uncertain``). Plain strings carry no label, so they are marked
``uncertain`` and flagged ``unlabeled``. The handoff is untrusted like every other
input: it is size-limited, validated, redacted and checked for injection patterns
later in the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import safepath
from .errors import ContextBridgeError, UnsafePathError
from .model import FLAG_UNLABELED, STATUSES, UNCERTAIN, Item

MAX_HANDOFF_BYTES = 64 * 1024
MAX_ENTRIES = 50
MAX_TEXT = 1000
MAX_FILES = 30

# handoff key -> (section, single value?, text prefix)
FIELDS: dict[str, tuple[str, bool, str]] = {
    "goal": ("goals", True, ""),
    "goals": ("goals", False, ""),
    "status": ("state", True, "Status: "),
    "state": ("state", False, "Status: "),  # list form; the pack section is called state
    "done": ("state", False, "Done: "),
    "constraints": ("constraints", False, ""),
    "decisions": ("decisions", False, ""),
    "next_steps": ("next_steps", False, ""),
    "open_questions": ("open_questions", False, ""),
}
_EXTRA_KEYS = {"files_touched", "author"}


class HandoffError(ContextBridgeError):
    """The session handoff is not valid; nothing was written."""


def _entry(value: Any, where: str, allow_reason: bool) -> tuple[str, str, bool]:
    """Return (text, status, labeled)."""
    if isinstance(value, str):
        text, status, labeled = value, UNCERTAIN, False
    elif isinstance(value, dict):
        unknown = set(value) - {"text", "status"} - ({"reason"} if allow_reason else set())
        if unknown:
            raise HandoffError(f"handoff {where}: unknown keys {sorted(unknown)}")
        text, status = value.get("text"), value.get("status")
        if not isinstance(text, str):
            raise HandoffError(f"handoff {where}: 'text' must be a string")
        if status not in STATUSES:
            raise HandoffError(f"handoff {where}: 'status' must be one of {', '.join(STATUSES)}")
        reason = value.get("reason")
        if reason is not None:
            if not isinstance(reason, str):
                raise HandoffError(f"handoff {where}: 'reason' must be a string")
            text = f"{text} (reason: {reason})" if reason.strip() else text
        labeled = True
    else:
        raise HandoffError(f"handoff {where}: entries must be strings or objects")
    text = " ".join(text.split())
    if not text:
        raise HandoffError(f"handoff {where}: empty text")
    if len(text) > MAX_TEXT:
        raise HandoffError(f"handoff {where}: text longer than {MAX_TEXT} characters")
    return text, status, labeled


def _relative(path: str, root: Path) -> str | None:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            return None
    try:
        return str(safepath.check_relative(path))
    except UnsafePathError:
        return None


def parse(raw: bytes, root: Path, source_id: str) -> tuple[list[Item], list[str], str | None]:
    """Validate a handoff. Returns (items, warnings, author)."""
    if len(raw) > MAX_HANDOFF_BYTES:
        raise HandoffError(f"handoff is larger than {MAX_HANDOFF_BYTES // 1024} KiB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"handoff is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HandoffError("handoff must be a JSON object")

    warnings = [f"handoff: unknown field '{key}' ignored" for key in sorted(set(data) - set(FIELDS) - _EXTRA_KEYS)]
    items: list[Item] = []
    for key, (section, single, prefix) in FIELDS.items():
        if key not in data:
            continue
        values = [data[key]] if single else data[key]
        if not isinstance(values, list):
            raise HandoffError(f"handoff '{key}' must be a list")
        if len(values) > MAX_ENTRIES:
            raise HandoffError(f"handoff '{key}' has more than {MAX_ENTRIES} entries")
        for index, value in enumerate(values):
            text, status, labeled = _entry(value, f"'{key}'[{index}]", allow_reason=key == "decisions")
            item = Item(section, prefix + text, status, source_id, f"handoff.{key}", order=len(items), origin_rank=0)
            if not labeled:
                item.add_flag(FLAG_UNLABELED)
            items.append(item)

    files = data.get("files_touched", [])
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise HandoffError("handoff 'files_touched' must be a list of strings")
    kept = []
    for path in files[:MAX_FILES]:
        rel = _relative(path, root)
        if rel is None:
            warnings.append("handoff: a file outside the project was left out of 'files_touched'")
        elif rel not in kept:
            kept.append(rel)
    if kept:
        items.append(Item("state", "Files touched in the session: " + ", ".join(kept), "fact", source_id,
                          "handoff.files_touched", order=len(items), origin_rank=0))  # fmt: skip

    author = data.get("author")
    if author is not None and (not isinstance(author, str) or not 0 < len(author) <= 40):
        raise HandoffError("handoff 'author' must be a short string")
    return items, warnings, author
