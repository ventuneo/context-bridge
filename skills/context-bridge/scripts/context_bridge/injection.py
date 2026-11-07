"""Prompt-injection heuristics, invisible-Unicode removal and delimiter neutralising.

Detection is heuristic and incomplete by design. The actual defence is layered:
packs are always presented as untrusted data, the skill never follows instructions
found in them, and these heuristics only add visible warnings. Findings never contain
the matched text, so a report cannot itself carry an injection.

Known gaps: homoglyphs (e.g. Cyrillic letters inside English words), instructions
split across many lines, and languages other than English and German.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# Zero-width, bidi controls, invisible operators, BOM, Mongolian vowel separator,
# Arabic letter mark and the Unicode "tag" block used for ASCII smuggling.
_INVISIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x061C, 0x061C), (0x180E, 0x180E), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x2064), (0x2066, 0x2069), (0xFEFF, 0xFEFF), (0xE0000, 0xE007F),
)  # fmt: skip
_TAG_RANGE = (0xE0000, 0xE007F)
_INVISIBLE_RE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _INVISIBLE_RANGES) + "]")

_FLAGS = re.IGNORECASE | re.MULTILINE
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (pid, severity, re.compile(rx, _FLAGS))
    for pid, severity, rx in (
        (
            "ignore_previous_instructions",
            HIGH,
            r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b(?:previous|prior|above|earlier|preceding|all|"
            r"any|your|the)\b.{0,40}\b(?:instructions?|prompts?|messages?|rules|guidelines|directions|context)\b",
        ),
        (
            "role_override",
            HIGH,
            r"\b(?:you are now|from now on,? you|act as (?:an?|the) |pretend (?:to be|you are)|"
            r"new (?:instructions|rules|persona)\s*:|your new (?:task|role|instructions))",
        ),
        (
            "system_prompt_reference",
            MEDIUM,
            r"\b(?:system prompt|developer message|system message|jailbreak|do anything now)\b",
        ),
        (
            "chat_role_markup",
            HIGH,
            r"<\s*/?\s*(?:system|assistant|user|developer|instructions?|context_bridge_pack)\b[^>]*>|"
            r"\[/?(?:inst|sys)\]|<\|(?:im_start|im_end|system|assistant|user|endoftext)\|>",
        ),
        ("role_label", MEDIUM, r"^\s*(?:#{1,6}\s*)?(?:system|assistant)\s*:"),
        (
            "command_execution",
            HIGH,
            r"\b(?:run|execute|exec)\b.{0,30}\b(?:the following|this|these)\b.{0,20}\b(?:commands?|scripts?|code)\b|"
            r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:ba|z)?sh\b|\brm\s+-rf\s+[/~]",
        ),
        (
            "exfiltration",
            HIGH,
            r"\b(?:send|upload|post|exfiltrate|leak|forward)\b.{0,60}\b(?:secrets?|credentials?|tokens?|api keys?|"
            r"passwords?|private keys?|\.env|ssh keys?)\b",
        ),
        (
            "ignore_previous_instructions_de",
            HIGH,
            r"\b(?:ignoriere|ignorier|missachte|vergiss|übergehe)\b.{0,40}\b(?:vorherigen|bisherigen|obigen|vorigen|"
            r"alle|alles|deine)\b.{0,40}\b(?:anweisungen|anweisung|befehle|regeln|vorgaben|instruktionen)\b",
        ),
        (
            "role_override_de",
            HIGH,
            r"\b(?:du bist (?:jetzt|ab sofort|nun|ab jetzt)|ab sofort bist du|neue anweisungen\s*:|"
            r"deine neue (?:aufgabe|rolle))",
        ),
        (
            "command_execution_de",
            HIGH,
            r"\bführe?\b.{0,30}\b(?:folgenden?|diesen?|dieses)\b.{0,20}\b(?:befehle?|skripte?|code)\b.{0,10}\baus\b",
        ),
        (
            "exfiltration_de",
            HIGH,
            r"\b(?:sende|schicke|lade|übermittle)\b.{0,60}\b(?:geheimnisse|zugangsdaten|passwörter|tokens?|"
            r"schlüssel|api-schlüssel)\b",
        ),
        ("remote_image_with_query", LOW, r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*\)"),
    )
)
_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
_DELIMITER_RE = re.compile(r"<(\s*/?\s*context_bridge_pack)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    type: str
    severity: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "severity": self.severity, "line": self.line}


def strip_invisible(text: str) -> tuple[str, list[Finding]]:
    """Remove invisible characters. Reports one finding per affected line."""
    findings: list[Finding] = []
    lines_seen: set[tuple[str, int]] = set()
    for match in _INVISIBLE_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        is_tag = _TAG_RANGE[0] <= ord(match.group(0)) <= _TAG_RANGE[1]
        kind = "unicode_tag_characters" if is_tag else "invisible_unicode"
        if (kind, line) not in lines_seen:
            lines_seen.add((kind, line))
            findings.append(Finding(kind, HIGH if is_tag else MEDIUM, line))
    return _INVISIBLE_RE.sub("", text), findings


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", _INVISIBLE_RE.sub("", text)).casefold()


def detect(text: str) -> list[Finding]:
    """Flag instruction-like content. ``text`` is not modified."""
    findings: set[Finding] = set()
    for lineno, line in enumerate(_normalise(text).splitlines(), start=1):
        for pid, severity, pattern in _PATTERNS:
            if pattern.search(line):
                findings.add(Finding(pid, severity, lineno))
    for comment in _HTML_COMMENT_RE.finditer(text):
        body = re.sub(r"\s+", " ", _normalise(comment.group(1)))
        if any(sev == HIGH and pat.search(body) for _pid, sev, pat in _PATTERNS):
            findings.add(Finding("hidden_instruction_in_comment", HIGH, text.count("\n", 0, comment.start()) + 1))
    return sorted(findings, key=lambda f: (f.line, f.type))


def neutralize_delimiters(text: str) -> str:
    """Escape anything that could open or close the pack wrapper tag."""
    return _DELIMITER_RE.sub(r"&lt;\1", text)
