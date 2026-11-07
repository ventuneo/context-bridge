"""verify: check a context pack's structure, integrity, safety and freshness.

1. **Structure**: ``schema.validate``. Any problem stops verification (exit 2).
2. **Integrity**: fingerprint, content hash, pack id and the Markdown hash are
   recomputed; the Markdown is re-rendered from the JSON and compared.
3. **Safety**: the finished pack is scanned again: secrets, personal data (when the
   pack was made with redaction), hidden characters, wrapper delimiters, instruction-
   like text without its warning flag, an altered trust notice and unsafe source paths.
4. **Freshness and provenance**: every file source is compared with the current file.
   For an *unchanged* file, every item must be re-derivable by the same extractor;
   an item that is not is reported as forged (``item_not_in_source``). This also
   catches tampering where an attacker recomputed the hashes. For a *changed* file,
   items that no longer appear are listed as outdated. Git commits, the file list
   and the pack age are checked as well.

Exit codes: 0 ok, 1 warnings, 2 errors (the pack must not be used), 3 the pack records
critical information loss.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__, gitrun, injection, policy, redact, safepath, schema, store
from . import pack as pack_mod
from . import scan as scan_mod
from .config import load_config
from .errors import (
    EXIT_CRITICAL_LOSS,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_WARNINGS,
    ContextBridgeError,
    PolicyViolation,
    UnsafePathError,
)
from .extract import gitinfo, project
from .model import FLAG_INJECTION, FLAG_TRUNCATED, ORIGIN_EXTERNAL, ORIGIN_FILE, ORIGIN_FILE_LIST, ORIGIN_GIT
from .render import TRUST_NOTICE, render_markdown

MAX_PACK_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_AGE_DAYS = 14
ERROR, CRITICAL, WARNING, INFO = "error", "critical", "warning", "info"
_DELIMITER = re.compile(r"<\s*/?\s*context_bridge_pack", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_COMMIT_ITEM = re.compile(r"^Recent commit ([0-9a-f]{4,40}) \((\d{4}-\d{2}-\d{2})\): (.*)$")
_UNSAFE_REASONS = {policy.SECRET_FILE, policy.SECRET_DIR, policy.PERSONAL_FILE, policy.NOISE_DIR}


class PackLoadError(ContextBridgeError):
    """No readable pack was found."""


@dataclass
class Finding:
    severity: str
    code: str
    detail: str
    source: str | None = None
    items: list[str] = field(default_factory=list)


@dataclass
class SourceStatus:
    id: str
    origin: str
    label: str
    status: str  # fresh | changed | missing | not_checked | not_checkable
    outdated_items: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class VerifyReport:
    pack_path: str
    pack: dict[str, Any] | None = None
    markdown: str | None = None
    findings: list[Finding] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)
    new_commits: int = 0
    commits_since: list[tuple[str, str]] = field(default_factory=list)
    new_sources: list[str] = field(default_factory=list)
    age_days: float | None = None

    def add(
        self, severity: str, code: str, detail: str, source: str | None = None, items: list[str] | None = None
    ) -> None:
        self.findings.append(Finding(severity, code, detail, source, list(items or [])))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def outdated_items(self) -> list[str]:
        ids = {i for s in self.sources for i in s.outdated_items}
        return sorted(ids, key=lambda i: int(i[1:]))

    @property
    def exit_code(self) -> int:
        severities = {f.severity for f in self.findings}
        if ERROR in severities or self.pack is None:
            return EXIT_ERROR
        if CRITICAL in severities:
            return EXIT_CRITICAL_LOSS
        return EXIT_WARNINGS if WARNING in severities else EXIT_OK

    @property
    def result(self) -> str:
        return {
            EXIT_OK: "ok",
            EXIT_WARNINGS: "ok_with_warnings",
            EXIT_CRITICAL_LOSS: "critical_information_loss",
            EXIT_ERROR: "failed",
        }[self.exit_code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "exit_code": self.exit_code,
            "pack_path": self.pack_path,
            "pack_id": (self.pack or {}).get("pack_id"),
            "age_days": self.age_days,
            "findings": [asdict(f) for f in self.findings],
            "sources": [asdict(s) for s in self.sources],
            "outdated_items": self.outdated_items,
            "new_commits": self.new_commits,
            "commits_since": [{"sha": sha, "subject": subject} for sha, subject in self.commits_since],
            "new_sources": self.new_sources,
        }


# ---------------------------------------------------------------------------
# Loading


def _load(root: Path, pack_arg: str | None) -> tuple[str, bytes, str | None]:
    """Return (display path, JSON bytes, Markdown text or None)."""
    if pack_arg is None or store.PACK_NAME_RE.match(f"{pack_arg}.json"):
        rel = (
            f"{store.STORE_DIR}/latest.json"
            if pack_arg is None
            else f"{store.STORE_DIR}/{store.PACKS_DIR}/{pack_arg}.json"
        )
        try:
            raw = safepath.read_file(root, rel, MAX_PACK_BYTES).data
        except UnsafePathError as exc:
            if exc.reason == safepath.MISSING:
                raise PackLoadError(f"no pack found at {rel}; run 'pack' first") from exc
            raise PackLoadError(f"pack refused ({exc.reason}): {rel}") from exc
        try:
            md_text: str | None = safepath.read_file(root, rel[:-5] + ".md", MAX_PACK_BYTES).data.decode("utf-8")
        except (UnsafePathError, UnicodeDecodeError):
            md_text = None
        return rel, raw, md_text
    path = Path(pack_arg).expanduser()
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_PACK_BYTES + 1)
    except OSError as exc:
        raise PackLoadError(f"cannot read pack: {exc}") from exc
    if len(raw) > MAX_PACK_BYTES:
        raise PackLoadError("pack is larger than 4 MiB")
    md_path = path.with_suffix(".md")
    try:
        md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
    except (OSError, UnicodeDecodeError):
        md_text = None
    return str(path), raw, md_text


# ---------------------------------------------------------------------------
# Checks


def _items(pack: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(section["key"], item) for section in pack["sections"] for item in section["items"]]


def _check_integrity(report: VerifyReport, pack: dict[str, Any], markdown: str | None, rel: str, root: Path) -> None:
    integrity = pack["integrity"]
    if pack_mod.fingerprint(pack) != integrity["fingerprint"]:
        report.add(ERROR, "fingerprint_mismatch", "the pack content does not match its fingerprint")
    if pack_mod.content_hash(pack) != integrity["content_hash"]:
        report.add(ERROR, "content_hash_mismatch", "the pack was modified after it was written")
    expected_id = pack["created_at"].replace("-", "").replace(":", "") + "-" + integrity["fingerprint"][:6]
    if pack["pack_id"] != expected_id:
        report.add(ERROR, "pack_id_mismatch", "the pack id does not match its timestamp and fingerprint")
    if markdown is None:
        report.add(WARNING, "markdown_missing", "the Markdown file is missing; resume renders it from the JSON")
    elif hashlib.sha256(markdown.encode("utf-8")).hexdigest() != integrity["markdown_sha256"]:
        report.add(ERROR, "markdown_modified", "the Markdown file was modified after it was written")
    elif render_markdown(pack) != markdown:
        report.add(WARNING, "renderer_changed", "this version renders the pack differently than the stored Markdown")
    if pack["generator"]["version"] != __version__:
        report.add(
            INFO, "generator_version_differs", f"pack made by {pack['generator']['version']}, checked by {__version__}"
        )
    if rel == f"{store.STORE_DIR}/latest.json":
        archived = root / store.STORE_DIR / store.PACKS_DIR / f"{pack['pack_id']}.json"
        try:
            if archived.is_file() and json.loads(archived.read_text(encoding="utf-8")) != pack:
                report.add(WARNING, "latest_differs_from_archive", "latest.json differs from the archived pack")
        except (OSError, ValueError):
            report.add(WARNING, "latest_differs_from_archive", "the archived pack cannot be read")


def _check_text(text: str, redact_pii: bool) -> list[str]:
    """Return problem codes for one piece of untrusted pack text."""
    problems = []
    if any(f.kind == redact.SECRET for f in redact.find(text, pii=False)):
        problems.append("secret_in_pack")
    if redact_pii and any(f.kind == redact.PII for f in redact.find(text, pii=True)):
        problems.append("personal_data_in_pack")
    if _DELIMITER.search(text):
        problems.append("delimiter_in_pack")
    if _CONTROL.search(text) or injection.strip_invisible(text)[1]:
        problems.append("hidden_characters")
    return problems


def _check_safety(report: VerifyReport, pack: dict[str, Any], root: Path, deny: policy.DenyRoots) -> None:
    trust = pack["trust"]
    if trust["content_is_untrusted_data"] is not True or trust["notice"] != TRUST_NOTICE:
        report.add(ERROR, "trust_notice_altered", "the pack no longer declares its content as untrusted data")
    redact_pii = pack["privacy"]["redact_pii"]
    found: dict[str, list[str]] = {}
    for _section, item in _items(pack):
        for code in _check_text(item["text"], redact_pii):
            found.setdefault(code, []).append(item["id"])
        if injection.detect(item["text"]) and FLAG_INJECTION not in item["flags"]:
            found.setdefault("unflagged_instruction", []).append(item["id"])
    others = [pack["project"]["name"], pack["project"]["root_label"]]
    others += [e["preview"] for e in pack["critical_loss"]] + [w["detail"] for w in pack["warnings"]]
    for text in others:
        for code in _check_text(text, redact_pii):
            found.setdefault(code, [])
    for code, ids in found.items():
        where = f"items {', '.join(ids[:10])}" if ids else "pack metadata"
        report.add(ERROR, code, f"unsafe content in {where}", items=ids)

    for source in pack["sources"]:
        label = source["label"]
        if _DELIMITER.search(label) or any(f.kind == redact.SECRET for f in redact.find(label, pii=False)):
            report.add(ERROR, "unsafe_source_label", f"source {source['id']} has an unsafe label", source["id"])
        elif _CONTROL.search(label):
            report.add(WARNING, "unusual_source_label", f"source {source['id']} has control characters", source["id"])
        if source["origin"] == ORIGIN_FILE:
            try:
                safepath.check_relative(label)
                unsafe = policy.classify(label).reason in _UNSAFE_REASONS or (deny and deny.blocks(root / label))
            except UnsafePathError:
                unsafe = True
            if unsafe:
                report.add(
                    ERROR, "unsafe_source_path", f"source {source['id']} points to a forbidden path", source["id"]
                )
        elif source["origin"] == ORIGIN_EXTERNAL:
            if not (label.startswith("~/") or "/" not in label) or ".." in label.split("/"):
                report.add(ERROR, "unsafe_source_path", f"source {source['id']} has an invalid label", source["id"])


def _check_quality(report: VerifyReport, pack: dict[str, Any]) -> None:
    if pack["critical_loss"]:
        sections = Counter(entry["section"] for entry in pack["critical_loss"])
        detail = ", ".join(f"{k} {v}" for k, v in sorted(sections.items()))
        report.add(
            CRITICAL,
            "critical_information_loss",
            f"{len(pack['critical_loss'])} critical item(s) were dropped or shortened when packing: {detail}",
        )
    if pack["budget"]["exceeded_to_protect_critical"]:
        report.add(
            INFO, "budget_exceeded_to_protect_critical", "the pack is larger than its budget to keep all critical items"
        )


def _reproduced(
    item: dict[str, Any], candidates: list[tuple[str, str, str, tuple[int, int] | None]], section: str, exact: bool
) -> bool:
    """Is a pack item still derivable? ``exact`` also requires extractor and lines to match."""
    text = item["text"]
    lines = tuple(item["lines"]) if "lines" in item else None
    truncated = FLAG_TRUNCATED in item["flags"]
    for c_section, c_extractor, c_text, c_lines in candidates:
        if c_section != section:
            continue
        if exact and (c_extractor != item["extractor"] or c_lines != lines):
            continue
        if c_text == text or (truncated and text.endswith("…") and c_text.startswith(text[:-1])):
            return True
    return False


def _sanitised(items: list, redact_pii: bool) -> list[tuple[str, str, str, tuple[int, int] | None]]:
    pack_mod.sanitise_items(items, redact_pii)
    return [(i.section, i.extractor, i.text, i.lines) for i in items]


def _check_freshness(
    report: VerifyReport,
    pack: dict[str, Any],
    root: Path,
    user_config_path: Path | None,
    now: datetime,
    max_age_days: float,
) -> None:
    created = datetime.strptime(pack["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    report.age_days = round((now - created).total_seconds() / 86400, 1)
    if created > now + timedelta(minutes=5):
        report.add(WARNING, "created_in_the_future", "the pack's timestamp lies in the future")
    elif report.age_days > max_age_days:
        report.add(WARNING, "pack_old", f"the pack is {report.age_days:g} days old (limit {max_age_days:g})")

    scan_report = scan_mod.scan(root, user_config_path, keep_text=True)
    current = {f.path: f for f in scan_report.included}
    redact_pii = pack["privacy"]["redact_pii"]
    strict = pack["generator"]["version"] == __version__
    by_source: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for section, item in _items(pack):
        by_source.setdefault(item["source"], []).append((section, item))
    labels = {s["label"] for s in pack["sources"]}

    for source in pack["sources"]:
        sid, origin, label = source["id"], source["origin"], source["label"]
        items = by_source.get(sid, [])
        ids = [item["id"] for _s, item in items]
        if origin in (ORIGIN_FILE, ORIGIN_EXTERNAL):
            entry = current.get(label)
            if entry is None:
                reason = next((r for r, paths in scan_report.excluded.items() if label in paths), "missing")
                report.sources.append(SourceStatus(sid, origin, label, "missing", ids, reason))
                report.add(WARNING, "source_missing", f"{label} is no longer available ({reason})", sid, ids)
                continue
            fresh, _ = pack_mod.extract_source(entry.path, entry.kind, scan_report.texts.get(entry.path, ""), sid)
            candidates = _sanitised(fresh, redact_pii)
            if entry.sha256 == source.get("sha256"):
                forged = [
                    item["id"] for section, item in items if not _reproduced(item, candidates, section, exact=True)
                ]
                report.sources.append(SourceStatus(sid, origin, label, "fresh"))
                if forged:
                    report.add(
                        ERROR if strict else WARNING,
                        "item_not_in_source",
                        f"{len(forged)} item(s) cannot be derived from the unchanged file {label}",
                        sid,
                        forged,
                    )
            else:
                outdated = [
                    item["id"] for section, item in items if not _reproduced(item, candidates, section, exact=False)
                ]
                report.sources.append(SourceStatus(sid, origin, label, "changed", outdated))
                report.add(
                    WARNING,
                    "source_changed",
                    f"{label} changed since the pack; {len(outdated)} of {len(items)} item(s) are outdated",
                    sid,
                    outdated,
                )
        elif origin == ORIGIN_GIT:
            _check_git(report, source, items, root, scan_report.vcs, redact_pii, strict)
        elif origin == ORIGIN_FILE_LIST:
            paths = sorted(
                {f.path for f in scan_report.included if f.origin == "project"}
                | {p for reason in pack_mod.STRUCTURE_REASONS for p in scan_report.excluded.get(reason, [])}
            )
            candidates = _sanitised(project.structure_items(paths, sid), redact_pii)
            outdated = [
                item["id"] for section, item in items if not _reproduced(item, candidates, section, exact=False)
            ]
            report.sources.append(SourceStatus(sid, origin, label, "changed" if outdated else "fresh", outdated))
            if outdated:
                report.add(
                    INFO,
                    "structure_changed",
                    f"the file structure changed; {len(outdated)} item(s) outdated",
                    sid,
                    outdated,
                )
        else:  # session handoff: there is nothing to compare against
            report.sources.append(SourceStatus(sid, origin, label, "not_checkable"))

    pending_at_pack_time = " ".join(w["detail"] for w in pack["warnings"] if w["code"] == "sources_pending_approval")
    report.new_sources = sorted(p for p in current if p not in labels and p not in pending_at_pack_time)
    if report.new_sources:
        report.add(INFO, "new_sources_since_pack", f"{len(report.new_sources)} new source(s) are not in the pack")


def _check_git(
    report: VerifyReport,
    source: dict[str, Any],
    items: list[tuple[str, dict[str, Any]]],
    root: Path,
    vcs: str,
    redact_pii: bool,
    strict: bool,
) -> None:
    sid, label, ref = source["id"], source["label"], source.get("ref")
    if ref is not None and not gitinfo.GIT_REF_RE.match(ref):
        report.add(ERROR, "invalid_git_ref", "the pack contains an invalid git reference", sid)
        report.sources.append(SourceStatus(sid, ORIGIN_GIT, label, "not_checked", reason="invalid reference"))
        return
    if vcs != "git":
        report.sources.append(SourceStatus(sid, ORIGIN_GIT, label, "not_checked", reason=vcs))
        report.add(WARNING, "git_not_checked", f"git metadata could not be checked ({vcs})", sid)
        return
    info = gitinfo.collect(root)
    if info is None:
        report.sources.append(SourceStatus(sid, ORIGIN_GIT, label, "not_checked", reason="git unavailable"))
        return
    forged: list[str] = []
    for _section, item in items:
        match = _COMMIT_ITEM.match(item["text"])
        if not match:
            continue
        actual = gitinfo.commit_info(root, match.group(1))
        if actual is None:
            report.add(
                WARNING, "commit_not_found", f"commit {match.group(1)} is not in the repository", sid, [item["id"]]
            )
            continue
        candidates = _sanitised(
            gitinfo.git_items(gitinfo.GitInfo("", None, commits=[(match.group(1), *actual)]), sid), redact_pii
        )
        if not _reproduced(item, candidates, "state", exact=False):
            forged.append(item["id"])
    if forged:
        report.add(
            ERROR if strict else WARNING,
            "item_not_in_source",
            f"{len(forged)} commit item(s) do not match the repository",
            sid,
            forged,
        )
    current_status = _sanitised(gitinfo.git_items(info, sid)[:1], redact_pii)
    outdated = [
        item["id"]
        for section, item in items
        if item["extractor"] == "git.status" and not _reproduced(item, current_status, section, exact=False)
    ]
    head = info.head or ""
    moved = bool(ref) and not (head.startswith(ref) or ref.startswith(head))
    if moved and ref and gitinfo.ref_exists(root, ref) and gitinfo.is_ancestor(root, ref):
        report.new_commits, report.commits_since = gitinfo.commits_since(root, ref)
    elif moved:
        report.add(WARNING, "git_history_rewritten", "the pack's commit is no longer part of the current history", sid)
    elif not ref and head:  # the repository had no commits when the pack was made
        report.new_commits = int(gitrun.run_git(root, ["rev-list", "--count", "HEAD"]).strip() or 0)
    status = "changed" if (moved or outdated or (not ref and head)) else "fresh"
    report.sources.append(SourceStatus(sid, ORIGIN_GIT, label, status, outdated))
    if status == "changed":
        report.add(WARNING, "source_changed", f"git: {report.new_commits} new commit(s) since the pack", sid, outdated)


# ---------------------------------------------------------------------------
# Entry points


def verify(
    root_arg: str | Path,
    pack_arg: str | None = None,
    *,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    user_config_path: Path | None = None,
    now: datetime | None = None,
) -> VerifyReport:
    root = safepath.resolve_root(root_arg)
    deny = load_config(root, user_config_path, include_project=False).deny()
    if deny.blocks(root):
        raise PolicyViolation("the project root lies inside a denied location (privacy.deny_roots); nothing was read")
    rel, raw, markdown = _load(root, pack_arg)
    report = VerifyReport(pack_path=rel, markdown=markdown)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        report.add(ERROR, "pack_unreadable", "the pack is not valid UTF-8 JSON")
        return report
    problems = schema.validate(data)
    if problems:
        for problem in problems[:20]:
            report.add(ERROR, "schema_invalid", problem)
        return report
    report.pack = data
    _check_integrity(report, data, markdown, rel, root)
    _check_safety(report, data, root, deny)
    _check_quality(report, data)
    _check_freshness(report, data, root, user_config_path, now or datetime.now(UTC), max_age_days)
    return report


def format_text(report: VerifyReport) -> str:
    safe = scan_mod._safe
    pack = report.pack or {}
    words = {
        "ok": "OK",
        "ok_with_warnings": "OK with warnings",
        "failed": "FAILED - do not use this pack",
        "critical_information_loss": "CRITICAL INFORMATION LOSS recorded in this pack",
    }
    lines = [f"Context Bridge verify: {safe(report.pack_path)}"]
    if pack:
        lines.append(f"Pack {pack['pack_id']} · created {pack['created_at']} ({report.age_days:g} days ago)")
    lines.append(f"Result: {words[report.result]}")
    if report.sources:
        counts = Counter(s.status for s in report.sources)
        lines.append("Sources: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
        for s in report.sources:
            if s.status in ("changed", "missing"):
                extra = f" (outdated: {', '.join(s.outdated_items)})" if s.outdated_items else ""
                lines.append(f"  {s.id} {safe(s.label)}: {s.status}{extra}")
    if report.new_commits:
        lines.append(f"git: {report.new_commits} new commit(s) since the pack")
    if report.findings:
        lines.append("Findings:")
        lines += [f"  {f.severity}: {f.code} - {safe(f.detail)}" for f in report.findings]
    return "\n".join(lines)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("verify", help="check a pack's structure, integrity, safety and freshness")
    _add_common(p)
    p.set_defaults(handler=run_cli)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", default=".", help="project root (default: current directory)")
    p.add_argument("--pack", metavar="ID_OR_PATH", help="pack id or path to a pack JSON (default: latest)")
    p.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS, help="age warning limit (default 14)")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def run_cli(args: argparse.Namespace) -> int:
    report = verify(args.root, args.pack, max_age_days=args.max_age_days)
    if args.json:
        json.dump(report.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(format_text(report))
    return report.exit_code
