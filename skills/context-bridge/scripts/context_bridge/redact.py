"""Secret and personal-data detection and redaction.

Findings never contain the matched value, only its type, kind and line number, so a
report can be shown or stored without leaking what it found. Redaction replaces the
sensitive part with ``[REDACTED:<type>]``.

Detection is pattern-based and therefore incomplete; files that are likely to hold
secrets are excluded by name before they are ever read (see ``policy.py``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

SECRET = "secret"
PII = "pii"

_PLACEHOLDER_HINTS = (
    "your", "xxx", "example", "changeme", "placeholder", "dummy", "sample", "redacted",
    "<", ">", "$", "{{", "***", "...", "(", "os.environ", "process.env", "getenv",
)  # fmt: skip
_EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")
_EXAMPLE_TLDS = (".example", ".invalid", ".test", ".localhost")


def _not_placeholder(value: str) -> bool:
    folded = value.casefold()
    return not any(hint in folded for hint in _PLACEHOLDER_HINTS)


def _email_is_real(value: str) -> bool:
    domain = value.rsplit("@", 1)[-1].casefold()
    return domain not in _EXAMPLE_DOMAINS and not domain.endswith(_EXAMPLE_TLDS)


def iban_checksum_ok(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if not 15 <= len(compact) <= 34 or not compact.isalnum():
        return False
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


@dataclass(frozen=True)
class Detector:
    name: str
    kind: str
    pattern: re.Pattern[str]
    group: int = 0
    validate: Callable[[str], bool] | None = None


DETECTORS: tuple[Detector, ...] = (
    Detector(
        "private_key",
        SECRET,
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
            r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----|\Z)"
        ),
    ),
    Detector("aws_access_key_id", SECRET, re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b")),
    Detector(
        "github_token", SECRET, re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b")
    ),
    Detector("anthropic_api_key", SECRET, re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    Detector("openai_api_key", SECRET, re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    Detector("slack_token", SECRET, re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Detector("slack_webhook", SECRET, re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+")),
    Detector("stripe_key", SECRET, re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    Detector("google_api_key", SECRET, re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    Detector("npm_token", SECRET, re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    Detector("pypi_token", SECRET, re.compile(r"\bpypi-[A-Za-z0-9_\-]{50,}")),
    Detector("jwt", SECRET, re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    Detector(
        "url_credentials",
        SECRET,
        re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:([^\s/@]+)@", re.IGNORECASE),
        group=1,
        validate=_not_placeholder,
    ),
    Detector(
        "credential_assignment",
        SECRET,
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|private[_-]?key|token)\b[\"']?\s*[:=]\s*[\"']?([^\s\"'`,;]{8,})"
        ),
        group=1,
        validate=_not_placeholder,
    ),
    Detector(
        "email",
        PII,
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
        validate=_email_is_real,
    ),
    Detector(
        "iban",
        PII,
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
        validate=iban_checksum_ok,
    ),
    Detector("ahv_number", PII, re.compile(r"\b756\.\d{4}\.\d{4}\.\d{2}\b")),
    Detector(
        "phone",
        PII,
        re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}[ \-/]?(?:\(0\) ?)?\d{1,4}(?:[ \-/]?\d{2,4}){2,4}(?!\w)"),
    ),
    Detector("phone", PII, re.compile(r"(?<![\w.])0\d{2} ?\d{3} ?\d{2} ?\d{2}(?![\w.])")),
)


@dataclass(frozen=True)
class Finding:
    type: str
    kind: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "kind": self.kind, "line": self.line}


def _spans(text: str, pii: bool) -> list[tuple[int, int, Detector]]:
    candidates: list[tuple[int, int, int, Detector]] = []
    for index, detector in enumerate(DETECTORS):
        if detector.kind == PII and not pii:
            continue
        for match in detector.pattern.finditer(text):
            start, end = match.span(detector.group)
            value = match.group(detector.group)
            if start < 0 or (detector.validate and not detector.validate(value)):
                continue
            candidates.append((start, end, index, detector))
    # Earliest first; for equal starts prefer the longer span, then the earlier detector.
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0]), c[2]))
    chosen: list[tuple[int, int, Detector]] = []
    last_end = -1
    for start, end, _index, detector in candidates:
        if start >= last_end:
            chosen.append((start, end, detector))
            last_end = end
    return chosen


def find(text: str, pii: bool = True) -> list[Finding]:
    """Detect secrets (and PII if ``pii``) without changing the text."""
    return [Finding(d.name, d.kind, text.count("\n", 0, s) + 1) for s, _e, d in _spans(text, pii)]


def redact(text: str, pii: bool = True) -> tuple[str, list[Finding]]:
    """Return the text with every finding replaced by ``[REDACTED:<type>]``."""
    spans = _spans(text, pii)
    findings = [Finding(d.name, d.kind, text.count("\n", 0, s) + 1) for s, _e, d in spans]
    out: list[str] = []
    cursor = 0
    for start, end, detector in spans:
        out.append(text[cursor:start])
        out.append(f"[REDACTED:{detector.name}]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out), findings


def contains_private_key(text: str) -> bool:
    return DETECTORS[0].pattern.search(text) is not None
