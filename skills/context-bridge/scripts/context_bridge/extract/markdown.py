"""Deterministic extraction from Markdown files.

Headings (English and German) decide which pack section their bullets, paragraphs and
table rows belong to. ``Key: value`` lines such as ``Goal:``, ``Ziel:``, ``Decision:``
or ``Nächster Schritt:`` route a line directly. Unchecked task boxes become open tasks.
Shell code blocks under command-like headings become commands. HTML comments and YAML
front matter are ignored, so hidden text never becomes an item.

The status of an item is derived conservatively: assumption sections and
``Assumption:`` lines give ``assumption``; open-question sections, hedging words and
questions give ``uncertain``; everything else is a ``fact`` about what the file says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import ASSUMPTION, FACT, UNCERTAIN, Item

MAX_ITEMS_PER_FILE = 200
MAX_COMMAND_LINES = 8


def _rx(words: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:" + words + r")(?!\w)", re.IGNORECASE)


HEADING_SECTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("goals", _rx(r"goals?|objectives?|purpose|aims?|mission|vision|ziele?|zweck|zielsetzung")),
    ("next_steps", _rx(r"next steps?|up next|next|nächste schritte|nächster schritt|als nächstes")),
    (
        "constraints",
        _rx(
            r"constraints?|rules?|requirements?|limitations?|limits|restrictions?|guardrails?|policy|policies|"
            r"security|privacy|principles?|einschränkungen?|regeln?|vorgaben?|anforderungen?|grenzen|sicherheit|"
            r"datenschutz|freigaben?|prinzipien|grundsätze"
        ),
    ),
    ("decisions", _rx(r"decisions?|adrs?|rationale|entscheidungen?|begründung")),
    ("open_tasks", _rx(r"to-?dos?|tasks?|backlog|roadmap|milestones?|aufgaben|meilensteine|pendenzen")),
    (
        "open_questions",
        _rx(
            r"open questions?|questions?|unknowns?|risks?|assumptions?|offene fragen|fragen|risiken|annahmen|"
            r"unsicheres|offen"
        ),
    ),
    ("state", _rx(r"status|state|current state|progress|stand|fortschritt")),
    (
        "commands",
        _rx(
            r"commands?|usage|getting started|quick ?start|install(?:ation)?|setup|build(?:ing)?|run(?:ning)?|"
            r"tests?|testing|development|befehle|nutzung|entwicklung"
        ),
    ),
    ("conventions", _rx(r"conventions?|style|guidelines?|contributing|workflow|konventionen|stil|arbeitsweise")),
    ("structure", _rx(r"architecture|structure|layout|directory|folders?|architektur|struktur|aufbau|ordner")),
    ("stack", _rx(r"tech(?:nology)?(?: stack)?|stack|dependencies|technik|abhängigkeiten")),
    ("overview", _rx(r"overview|about|introduction|description|summary|überblick|beschreibung|einleitung")),
)
_ASSUMPTION_HEADING = _rx(r"assumptions?|annahmen?")
_UNCERTAIN_HEADING = _rx(
    r"open questions?|questions?|unknowns?|risks?|unsicheres|unsicherheiten|offene fragen|fragen|risiken|offen"
)
_HEDGE = _rx(
    r"maybe|perhaps|might|probably|possibly|unclear|unknown|unsure|tbd|to be decided|not sure|vielleicht|"
    r"eventuell|evtl\.?|wahrscheinlich|möglicherweise|unklar|unbekannt|unsicher|noch offen|ungeklärt"
)
_ASSUMPTION_PREFIX = re.compile(r"^(?:annahme|assumption)\s*:", re.IGNORECASE)
_OPEN_PREFIX = re.compile(r"^(?:offen|open|unsicher|uncertain|frage|question)\s*:", re.IGNORECASE)

KEY_SECTIONS: dict[str, str] = {
    "ziel": "goals",
    "ziele": "goals",
    "goal": "goals",
    "goals": "goals",
    "objective": "goals",
    "status": "state",
    "stand": "state",
    "state": "state",
    "nächster schritt": "next_steps",
    "nächste schritte": "next_steps",
    "next step": "next_steps",
    "next steps": "next_steps",
    "entscheidung": "decisions",
    "decision": "decisions",
    "einschränkung": "constraints",
    "einschränkungen": "constraints",
    "constraint": "constraints",
    "constraints": "constraints",
    "annahme": "open_questions",
    "assumption": "open_questions",
    "offen": "open_questions",
    "open question": "open_questions",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)")
_BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,3}[.)])\s+(.*\S)\s*$")
_CHECKBOX_RE = re.compile(r"^\[( |x|X)\]\s+(.*)$")
_KV_RE = re.compile(r"^\**([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü .\-]{1,28}?)\**\s*:\**\s+(\S.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_QUOTE_RE = re.compile(r"^\s*(?:>\s?)+")
_SHELL_LANGS = {"", "sh", "bash", "zsh", "shell", "console", "fish", "powershell", "ps1", "cmd"}


def classify_heading(text: str) -> tuple[str | None, str | None]:
    """Return (section key or None, status override or None) for a heading."""
    status = ASSUMPTION if _ASSUMPTION_HEADING.search(text) else UNCERTAIN if _UNCERTAIN_HEADING.search(text) else None
    for key, pattern in HEADING_SECTIONS:
        if pattern.search(text):
            return key, status
    return None, status


def status_for(text: str, inherited: str | None) -> str:
    if _ASSUMPTION_PREFIX.match(text):
        return ASSUMPTION
    if _OPEN_PREFIX.match(text) or _HEDGE.search(text) or text.rstrip().endswith("?"):
        return UNCERTAIN
    return inherited or FACT


def _is_key_line(line: str) -> bool:
    match = _KV_RE.match(_QUOTE_RE.sub("", line).strip())
    return bool(match) and match.group(1).strip().casefold() in KEY_SECTIONS


def _strip_hidden(text: str) -> str:
    """Blank out HTML comments and YAML front matter but keep line numbers."""
    text = _HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = "\n" * text[: end + 4].count("\n") + text[end + 4 :]
    return text


@dataclass
class _Context:
    section: str | None
    status: str | None


@dataclass
class _Block:
    kind: str  # bullet | para
    lines: list[str]
    start: int
    end: int
    indent: int = 0


class _Extractor:
    def __init__(self, source_id: str, file_kind: str, origin_rank: int) -> None:
        self.source_id = source_id
        self.file_kind = file_kind
        self.origin_rank = origin_rank
        self.items: list[Item] = []
        self.stack: list[tuple[int, _Context]] = []
        self.title: tuple[str, int] | None = None
        self.seen_subheading = False
        self.overview_done = False

    @property
    def context(self) -> _Context:
        return self.stack[-1][1] if self.stack else _Context(None, None)

    def add(self, section: str, text: str, status: str, extractor: str, start: int, end: int) -> None:
        if len(self.items) >= MAX_ITEMS_PER_FILE or not text:
            return
        self.items.append(
            Item(
                section=section,
                text=text,
                status=status,
                source=self.source_id,
                extractor=extractor,
                lines=(start, end),
                order=len(self.items),
                origin_rank=self.origin_rank,
            )
        )

    def heading(self, level: int, text: str, lineno: int) -> None:
        if level == 1 and self.title is None:
            self.title = (text, lineno)
        if level >= 2:
            self.seen_subheading = True
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        section, status = classify_heading(text)
        parent = self.context
        self.stack.append((level, _Context(section or parent.section, status or parent.status)))

    def block(self, block: _Block) -> None:
        text = " ".join(_QUOTE_RE.sub("", part).strip() for part in block.lines)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        ctx = self.context
        if block.kind == "bullet":
            box = _CHECKBOX_RE.match(text)
            if box:
                if box.group(1) == " ":
                    self.add(
                        "open_tasks",
                        box.group(2),
                        status_for(box.group(2), ctx.status),
                        "markdown.task",
                        block.start,
                        block.end,
                    )
                return
        kv = _KV_RE.match(text)
        if kv and kv.group(1).strip().casefold() in KEY_SECTIONS:
            section = KEY_SECTIONS[kv.group(1).strip().casefold()]
            self.add(section, text, status_for(text, ctx.status), "markdown.key_value", block.start, block.end)
            return
        if ctx.section:
            self.add(ctx.section, text, status_for(text, ctx.status), f"markdown.{block.kind}", block.start, block.end)
        elif self.file_kind == "agent_rules" and block.kind == "bullet":
            self.add("conventions", text, status_for(text, ctx.status), "markdown.bullet", block.start, block.end)
        elif (
            self.file_kind == "readme"
            and block.kind == "para"
            and not self.seen_subheading
            and not self.overview_done
            and not text.startswith(("![", "[!["))  # badges
        ):
            self.overview_done = True
            self.add("overview", text, status_for(text, None), "markdown.first_paragraph", block.start, block.end)

    def table_row(self, cells: list[str], lineno: int) -> None:
        ctx = self.context
        text = " · ".join(c for c in (cell.strip() for cell in cells) if c)
        if ctx.section and text:
            self.add(ctx.section, text, status_for(text, ctx.status), "markdown.table_row", lineno, lineno)

    def code(self, lang: str, lines: list[tuple[int, str]]) -> None:
        if self.context.section != "commands" or lang.casefold() not in _SHELL_LANGS:
            return
        taken = 0
        for lineno, raw in lines:
            command = raw.strip().removeprefix("$ ").strip()
            if command and not command.startswith("#") and taken < MAX_COMMAND_LINES:
                self.add("commands", command, FACT, "markdown.code", lineno, lineno)
                taken += 1


def extract(text: str, source_id: str, file_kind: str, origin_rank: int) -> tuple[list[Item], str | None]:
    """Extract items from Markdown ``text``. Returns (items, H1 title or None)."""
    ex = _Extractor(source_id, file_kind, origin_rank)
    lines = _strip_hidden(text).splitlines()
    block: _Block | None = None
    fence: tuple[str, str, list[tuple[int, str]]] | None = None
    i = 0

    def flush() -> None:
        nonlocal block
        if block:
            ex.block(block)
            block = None

    while i < len(lines):
        lineno, line = i + 1, lines[i]
        if fence:
            if line.strip().startswith(fence[0]):
                ex.code(fence[1], fence[2])
                fence = None
            else:
                fence[2].append((lineno, line))
            i += 1
            continue
        if m := _FENCE_RE.match(line):
            flush()
            fence = (m.group(1), m.group(2), [])
        elif m := _HEADING_RE.match(line):
            flush()
            ex.heading(len(m.group(1)), m.group(2), lineno)
        elif not line.strip():
            flush()
        elif _TABLE_ROW_RE.match(line):
            flush()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not _TABLE_SEP_RE.match(line) and not _TABLE_SEP_RE.match(nxt):
                ex.table_row(_TABLE_ROW_RE.match(line).group(1).split("|"), lineno)  # type: ignore[union-attr]
        elif m := _BULLET_RE.match(line):
            flush()
            block = _Block("bullet", [m.group(2)], lineno, lineno, len(m.group(1)))
        elif _is_key_line(line):
            flush()  # consecutive 'Goal: …' / 'Status: …' lines are separate items
            block = _Block("para", [line], lineno, lineno)
        elif block and (block.kind == "para" or len(line) - len(line.lstrip()) > block.indent):
            block.lines.append(line)
            block.end = lineno
        else:
            flush()
            block = _Block("para", [line], lineno, lineno)
        i += 1
    flush()

    title = ex.title[0] if ex.title else None
    if file_kind == "decisions" and ex.title and not any(it.section == "decisions" for it in ex.items):
        ex.add("decisions", ex.title[0], status_for(ex.title[0], None), "markdown.title", ex.title[1], ex.title[1])
    return ex.items, title
