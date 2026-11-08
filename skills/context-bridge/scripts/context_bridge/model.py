"""Data model of a context pack: sections, tiers, statuses, sources and items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PACK_FORMAT = "context-bridge.pack"
SCHEMA_VERSION = "1.1"  # 1.1: section "unclassified", flag "inferred", the "extraction" report

# Tiers decide what is dropped first when the budget is tight (context first).
CRITICAL = "critical"
IMPORTANT = "important"
CONTEXT = "context"
TIER_RANK = {CRITICAL: 0, IMPORTANT: 1, CONTEXT: 2}

# Every item says how sure it is. Files state facts about themselves; hedged text,
# assumption sections and open questions are marked so a reader can tell them apart.
FACT = "fact"
ASSUMPTION = "assumption"
UNCERTAIN = "uncertain"
STATUSES = (FACT, ASSUMPTION, UNCERTAIN)

# Item flags (stable: they appear in packs).
FLAG_REDACTED = "redacted"
FLAG_INJECTION = "instruction_like"
FLAG_TRUNCATED = "truncated"
FLAG_UNLABELED = "unlabeled"
FLAG_INFERRED = "inferred"  # sorted by its wording (decided, TODO, Ziel ist …), not by a heading


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    tier: str
    max_items: int | None  # None: limited only by the token budget (critical sections)


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec("goals", "Goals", CRITICAL, None),
    SectionSpec("constraints", "Constraints", CRITICAL, None),
    SectionSpec("decisions", "Decisions", CRITICAL, None),
    SectionSpec("next_steps", "Next steps", CRITICAL, None),
    SectionSpec("state", "Current state", IMPORTANT, 12),
    SectionSpec("open_questions", "Open questions and assumptions", IMPORTANT, 15),
    SectionSpec("open_tasks", "Open tasks", IMPORTANT, 20),
    SectionSpec("commands", "Commands", IMPORTANT, 12),
    SectionSpec("overview", "Overview", CONTEXT, 4),
    SectionSpec("conventions", "Conventions", CONTEXT, 15),
    SectionSpec("stack", "Stack", CONTEXT, 8),
    SectionSpec("structure", "Structure", CONTEXT, 15),
    # Text under headings that no rule recognises and that no wording sorts: kept as data, dropped first.
    SectionSpec("unclassified", "Unclassified notes", CONTEXT, 15),
)
SECTION_BY_KEY: dict[str, SectionSpec] = {spec.key: spec for spec in SECTION_SPECS}
SECTION_INDEX: dict[str, int] = {spec.key: i for i, spec in enumerate(SECTION_SPECS)}

# Source origins.
ORIGIN_FILE = "file"
ORIGIN_EXTERNAL = "external"
ORIGIN_GIT = "git"
ORIGIN_FILE_LIST = "file_list"
ORIGIN_SESSION = "session"


@dataclass
class Source:
    id: str
    origin: str
    label: str
    kind: str | None = None
    sha256: str | None = None
    size: int | None = None
    ref: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "origin": self.origin,
            "label": self.label,
            "kind": self.kind,
            "sha256": self.sha256,
            "size": self.size,
            "ref": self.ref,
            "created_at": self.created_at,
        }
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class Item:
    section: str
    text: str
    status: str
    source: str
    extractor: str
    lines: tuple[int, int] | None = None
    flags: list[str] = field(default_factory=list)
    order: int = 0  # document order inside its source, used for stable priority
    origin_rank: int = 9  # lower is preferred (session handoff first)
    also_in: list[str] = field(default_factory=list)  # sources of removed duplicates
    id: str = ""
    region: int | None = None  # index of the Markdown section it came from (extraction report only)

    @property
    def tier(self) -> str:
        return SECTION_BY_KEY[self.section].tier

    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "source": self.source,
            "extractor": self.extractor,
            "flags": list(self.flags),
        }
        if self.lines:
            data["lines"] = list(self.lines)
        if self.also_in:
            data["also_in"] = list(self.also_in)
        return data
