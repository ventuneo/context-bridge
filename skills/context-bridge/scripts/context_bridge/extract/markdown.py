"""Deterministic extraction from Markdown files.

Headings (English and German) decide which pack section their bullets, paragraphs and
table rows belong to. ``Key: value`` lines such as ``Goal:``, ``Ziel:``, ``Decision:``
or ``Nächster Schritt:`` route a line directly. Unchecked task boxes become open tasks.
Shell code blocks under command-like headings become commands. HTML comments and YAML
front matter are ignored, so hidden text never becomes an item.

Smart extraction: text under a heading that no rule recognises (and text before the first
heading) is not dropped. When its wording says what it is ("we decided", "TODO", "Ziel ist",
a question), it goes to that section with the flag ``inferred``; otherwise it becomes an
``unclassified`` note. Boilerplate sections (licence, credits, table of contents) are skipped.
Every Markdown section of a file is recorded as a :class:`Region` for the extraction report.

The status of an item is derived conservatively: assumption sections and
``Assumption:`` lines give ``assumption``; open-question sections, hedging words and
questions give ``uncertain``; everything else is a ``fact`` about what the file says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import ASSUMPTION, FACT, FLAG_INFERRED, UNCERTAIN, Item

MAX_ITEMS_PER_FILE = 200
MAX_SMART_ITEMS_PER_FILE = 60  # items from unrecognised sections, so one long note cannot crowd out the rest
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
            r"security|privacy|principles?|einschränkung(?:en)?|regeln?|vorgaben?|anforderung(?:en)?|grenzen|sicherheit|"
            r"datenschutz|freigaben?|prinzip(?:ien)?|grundsatz|grundsätze"
        ),
    ),
    ("decisions", _rx(r"decisions?|adrs?|rationale|entscheidung(?:en)?|begründung(?:en)?")),
    ("open_tasks", _rx(r"to-?dos?|tasks?|backlog|roadmap|milestones?|aufgaben?|meilensteine?|pendenz(?:en)?")),
    (
        "open_questions",
        _rx(
            r"open questions?|questions?|unknowns?|risks?|assumptions?|offene fragen|fragen?|risiko|risiken|annahmen?|"
            r"unsicheres|unsicherheit(?:en)?|offen"
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
    ("conventions", _rx(r"conventions?|style|guidelines?|contributing|workflow|konvention(?:en)?|stil|arbeitsweise")),
    ("structure", _rx(r"architecture|structure|layout|directory|folders?|architektur|struktur|aufbau|ordner")),
    ("stack", _rx(r"tech(?:nology)?(?: stack)?|stack|dependencies|technik|abhängigkeit(?:en)?")),
    ("overview", _rx(r"overview|about|introduction|description|summary|überblick|beschreibung|einleitung")),
)
# Boilerplate whose text is never packed; the extraction report lists such sections as skipped.
_SKIP_HEADING = _rx(
    r"licen[cs]es?|lizenz(?:en)?|credits?|acknowledge?ments?|danksagung(?:en)?|table of contents|contents|"
    r"inhalt|inhaltsverzeichnis|sponsors?|badges?|changelog|release notes|änderungsprotokoll"
)
# Wording that sorts text from unrecognised sections. Deliberately narrow: a sentence has to say
# what it is; everything else stays unclassified. Checked in this order.
_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "decisions",
        _rx(
            r"we (?:have |’ve |'ve )?(?:decided|chosen|agreed)|decided (?:to|against|on)|we chose|we went with|"
            r"the decision (?:is|was)|wir haben (?:uns )?(?:entschieden|beschlossen|geeinigt)|"
            r"(?:wurde|ist|haben) (?:uns )?(?:entschieden|beschlossen)|entschieden,? dass|haben uns (?:für|gegen)|"
            r"fiel die wahl auf"
        ),
    ),
    (
        "next_steps",
        _rx(
            r"next,? we|as a next step|the next step is|next up|als nächstes|als nächster schritt|"
            r"im nächsten schritt|der nächste schritt ist"
        ),  # fmt: skip
    ),
    (
        "open_tasks",
        _rx(
            r"todo|to-do|fixme|we (?:still )?(?:need|have) to|still (?:needs?|has|have) to|must still|"
            r"noch zu erledigen|muss noch|müssen noch|sollten? noch|wir müssen"
        ),
    ),
    (
        "goals",
        _rx(
            r"(?:the|our|main) (?:goal|aim|objective) (?:is|was)|we want to|we aim to|aims? to|"
            r"(?:das|unser) ziel ist|ziel ist es|wir wollen|wir möchten"
        ),  # fmt: skip
    ),
)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# Quoted text and inline code are examples or names, not what the author states: "we decided" in
# quotes is no decision. A single quote counts only when no letter touches it from outside, so the
# apostrophe in "we've" or "don't" never starts a quotation.
_QUOTED_RE = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|„[^“”\n]*[“”]|«[^»\n]*»|»[^«\n]*«|‹[^›\n]*›|‘[^’\n]*’|(?<!\w)\'[^\'\n]+\'(?!\w)|`[^`\n]*`'
)
# A sentence ends at . ! or ? (and closing quotes) before a capital letter or digit, except after an
# abbreviation (z. B., d. h., e.g., Nr.) or an ordinal number (1. Juli).
_SENTENCE_END = re.compile(r"[.!?]+[\"”“»)\]]*\s+(?=[\"„“«(\[]?[A-ZÄÖÜ0-9])")
_ABBREVIATIONS = frozenset(
    "a b d e h i o s u z ab abs bzw ca dr etc evtl ff ggf inkl mr mrs ms nr vgl vs bspw usw e.g i.e z.b d.h u.a".split()
)
NOTE_LINE = 60  # paragraphs with a shorter line (except the last) are notes: one statement per line
_ASSUMPTION_HEADING = _rx(r"assumptions?|annahmen?")
_UNCERTAIN_HEADING = _rx(
    r"open questions?|questions?|unknowns?|risks?|unsicheres|unsicherheit(?:en)?|offene fragen|fragen?|risiko|risiken|"
    r"offen"
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


def infer_section(text: str, questions: bool = True) -> str | None:
    """The section that the wording of ``text`` names (a decision, a task …), or None.

    Quoted text and inline code do not count. With ``questions=False`` (table rows, whose cells
    often hold questions as labels) a final question mark does not make an open question.
    """
    own = _QUOTED_RE.sub(" ", text)
    for key, pattern in _CUES:
        if pattern.search(own):
            return key
    return "open_questions" if questions and text.rstrip().endswith("?") else None


def sentences(text: str) -> list[tuple[int, int]]:
    """Spans (start, end) of the sentences of ``text``."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = text[start : match.start()].split()
        word = before[-1].casefold() if before else ""
        if word in _ABBREVIATIONS or (word.isdigit() and len(word) <= 2):
            continue
        spans.append((start, match.start() + len(match.group(0).rstrip())))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return spans


def _has_words(text: str) -> bool:
    """Real text, not a badge row, a rule (---) or a stray symbol."""
    return sum(ch.isalpha() for ch in _IMAGE_RE.sub("", text)) >= 3


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
    skipped: bool = False


@dataclass
class Region:
    """One Markdown section of a file: a heading with its text, or the text before the first heading."""

    heading: str | None  # None: before the first heading
    line: int
    section: str | None  # the pack section its heading maps to (also inherited from a parent heading)
    skipped: bool = False  # boilerplate such as a licence: never packed
    over_limit: int = 0  # blocks not extracted because the file reached an item limit


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
        self.regions: list[Region] = [Region(None, 1, None)]
        self.smart = 0

    @property
    def context(self) -> _Context:
        return self.stack[-1][1] if self.stack else _Context(None, None)

    def add(self, section: str, text: str, status: str, extractor: str, start: int, end: int,
            flags: tuple[str, ...] = (), region: int | None = None) -> None:  # fmt: skip
        region = len(self.regions) - 1 if region is None else region
        if not text:
            return
        if len(self.items) >= MAX_ITEMS_PER_FILE:
            self.regions[region].over_limit += 1
            return
        self.items.append(
            Item(
                section=section,
                text=text,
                status=status,
                source=self.source_id,
                extractor=extractor,
                lines=(start, end),
                flags=list(flags),
                order=len(self.items),
                origin_rank=self.origin_rank,
                region=region,
            )
        )

    def smart_item(self, text: str, ctx: _Context, start: int, end: int, questions: bool = True) -> None:
        """One statement that no heading sorts: by its wording, or as an unclassified note."""
        if ctx.skipped or not _has_words(text):
            return
        if self.smart >= MAX_SMART_ITEMS_PER_FILE:
            self.regions[-1].over_limit += 1
            return
        self.smart += 1
        section = infer_section(text, questions)
        if section:
            self.add(section, text, status_for(text, ctx.status), "markdown.cue", start, end, (FLAG_INFERRED,))
        else:
            self.add("unclassified", text, status_for(text, ctx.status), "markdown.unclassified", start, end)

    def smart_paragraph(self, block: _Block, ctx: _Context) -> None:
        """Split a paragraph without a recognised heading into statements and sort each one.

        Short lines are notes, one statement per line; wrapped prose is split into sentences.
        Neighbouring sentences of the same prose that no wording sorts stay together as one note.
        """
        parts = [(block.start + i, " ".join(_QUOTE_RE.sub("", line).split())) for i, line in enumerate(block.lines)]
        parts = [(n, text) for n, text in parts if text]
        if len(parts) > 1 and any(len(text) < NOTE_LINE for _n, text in parts[:-1]):
            units = [[(n, text)] for n, text in parts]
        else:
            units = [parts]
        for unit in units:
            joined, starts = "", []
            for n, text in unit:
                starts.append((len(joined) + (1 if joined else 0), n))
                joined = f"{joined} {text}" if joined else text
            pending: list[tuple[str, int, int]] = []
            for a, b in sentences(joined):
                sentence = joined[a:b].strip()
                first = max(n for offset, n in starts if offset <= a)
                last = max(n for offset, n in starts if offset < b)
                if infer_section(sentence):
                    self._flush_note(pending, ctx)
                    self.smart_item(sentence, ctx, first, last)
                else:
                    pending.append((sentence, first, last))
            self._flush_note(pending, ctx)

    def _flush_note(self, pending: list[tuple[str, int, int]], ctx: _Context) -> None:
        if pending:
            self.smart_item(" ".join(s for s, _a, _b in pending), ctx, pending[0][1], pending[-1][2])
            pending.clear()

    def heading(self, level: int, text: str, lineno: int) -> None:
        if level == 1 and self.title is None:
            self.title = (text, lineno)
        if level >= 2:
            self.seen_subheading = True
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        section, status = classify_heading(text)
        parent = self.context
        skipped = parent.skipped or (section is None and parent.section is None and bool(_SKIP_HEADING.search(text)))
        ctx = _Context(section or parent.section, status or parent.status, skipped)
        self.stack.append((level, ctx))
        self.regions.append(Region(text, lineno, ctx.section, ctx.skipped))

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
        elif block.kind == "para":
            self.smart_paragraph(block, ctx)
        else:
            self.smart_item(text, ctx, block.start, block.end)

    def table_row(self, cells: list[str], lineno: int) -> None:
        ctx = self.context
        text = " · ".join(c for c in (cell.strip() for cell in cells) if c)
        if ctx.section and text:
            self.add(ctx.section, text, status_for(text, ctx.status), "markdown.table_row", lineno, lineno)
        elif text:
            self.smart_item(text, ctx, lineno, lineno, questions=False)

    def code(self, lang: str, lines: list[tuple[int, str]]) -> None:
        if self.context.section != "commands" or lang.casefold() not in _SHELL_LANGS:
            return
        taken = 0
        for lineno, raw in lines:
            command = raw.strip().removeprefix("$ ").strip()
            if command and not command.startswith("#") and taken < MAX_COMMAND_LINES:
                self.add("commands", command, FACT, "markdown.code", lineno, lineno)
                taken += 1


def content_lines(text: str) -> set[int]:
    """Line numbers of text a reader reads: not blank, a heading, code, a table rule, hidden text,
    a badge row or a rule. The quality report measures how many of them end up in items."""
    lines: set[int] = set()
    fence = None
    for lineno, line in enumerate(_strip_hidden(text).splitlines(), start=1):
        if fence:
            fence = None if line.strip().startswith(fence) else fence
            continue
        if m := _FENCE_RE.match(line):
            fence = m.group(1)
        elif not (_HEADING_RE.match(line) or _TABLE_SEP_RE.match(line)) and _has_words(line):
            lines.add(lineno)
    return lines


def extract(text: str, source_id: str, file_kind: str, origin_rank: int,
            outline: list[Region] | None = None) -> tuple[list[Item], str | None]:  # fmt: skip
    """Extract items from Markdown ``text``. Returns (items, H1 title or None).

    ``outline``, if given, receives the file's sections; ``Item.region`` indexes into it.
    """
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
        region = next((i for i, r in enumerate(ex.regions) if r.heading is not None and r.line == ex.title[1]), 0)
        ex.add("decisions", ex.title[0], status_for(ex.title[0], None), "markdown.title", ex.title[1], ex.title[1],
               region=region)  # fmt: skip
    if outline is not None:
        outline.extend(ex.regions)
    return ex.items, title
