"""Structural validation of a context pack (schema 1.x), standard library only.

Mirrors ``schema/context-pack-v1.schema.json`` and adds the cross-references a JSON
Schema cannot express (items and warnings must point to existing sources, ids are
unique, sections follow the canonical order). Returns a list of problems; an empty
list means the structure is valid. Hashes, safety and freshness are checked in
``verify``.
"""

from __future__ import annotations

import re
from typing import Any

from .budget import COVERAGE_STATUSES
from .model import (
    CRITICAL,
    FLAG_INFERRED,
    FLAG_INJECTION,
    FLAG_REDACTED,
    FLAG_TRUNCATED,
    FLAG_UNLABELED,
    ORIGIN_EXTERNAL,
    ORIGIN_FILE,
    ORIGIN_FILE_LIST,
    ORIGIN_GIT,
    ORIGIN_SESSION,
    PACK_FORMAT,
    SECTION_BY_KEY,
    SECTION_INDEX,
    STATUSES,
)

SUPPORTED_MAJOR = "1"
MAX_TEXT = 4000
FLAGS = {FLAG_REDACTED, FLAG_INJECTION, FLAG_TRUNCATED, FLAG_UNLABELED, FLAG_INFERRED}
REGION_AS = {"unrecognised", "skipped"}  # besides the section keys
REGION_COUNTS = ("extracted", "kept", "merged", "shortened", "left_out", "inferred", "unclassified", "not_extracted")
ORIGINS = {ORIGIN_FILE, ORIGIN_EXTERNAL, ORIGIN_GIT, ORIGIN_FILE_LIST, ORIGIN_SESSION}
SEVERITIES = {"info", "warning", "critical"}
LOSS_REASONS = {"dropped", "truncated"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PACK_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SOURCE_ID = re.compile(r"^S[1-9]\d*$")
ITEM_ID = re.compile(r"^I[1-9]\d*$")
VERSION = re.compile(r"^(\d+)\.(\d+)$")


def _is(value: Any, kind: Any) -> bool:
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "str?":
        return value is None or isinstance(value, str)
    return isinstance(value, kind)


class _Validator:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.problems.append(f"{path}: {message}")

    def obj(self, value: Any, path: str, required: dict[str, Any], optional: dict[str, Any] | None = None) -> bool:
        optional = optional or {}
        if not isinstance(value, dict):
            self.error(path, "must be an object")
            return False
        for key, kind in required.items():
            if key not in value:
                self.error(f"{path}.{key}", "is missing")
            elif not _is(value[key], kind):
                self.error(f"{path}.{key}", "has the wrong type")
        for key, kind in optional.items():
            if key in value and not _is(value[key], kind):
                self.error(f"{path}.{key}", "has the wrong type")
        unknown = sorted(set(value) - set(required) - set(optional))
        if unknown:
            self.error(path, f"unknown keys {unknown}")
        return all(key in value and _is(value[key], kind) for key, kind in required.items())

    def match(self, value: Any, pattern: re.Pattern[str], path: str) -> None:
        if isinstance(value, str) and not pattern.match(value):
            self.error(path, "has an invalid format")

    def text(self, value: Any, path: str) -> None:
        if isinstance(value, str) and (not value.strip() or len(value) > MAX_TEXT):
            self.error(path, f"must be non-empty and at most {MAX_TEXT} characters")

    def lines(self, value: Any, path: str) -> None:
        ok = isinstance(value, list) and len(value) == 2 and all(_is(v, int) for v in value)
        if not ok or not 1 <= value[0] <= value[1]:
            self.error(path, "must be [start, end] with 1 <= start <= end")


def _validate_extraction(v: _Validator, report: dict[str, Any]) -> None:
    """The extraction report: per Markdown file, what each heading contributed (counts only)."""
    if not v.obj(report, "pack.extraction", {"sources": list}):
        return
    for s, source in enumerate(report["sources"]):
        path = f"pack.extraction.sources[{s}]"
        if not v.obj(source, path, {"label": str, "regions": list}):
            continue
        for r, region in enumerate(source["regions"]):
            rpath = f"{path}.regions[{r}]"
            if not v.obj(
                region,
                rpath,
                {"heading": "str?", "line": int, "as": str, "to": dict, **dict.fromkeys(REGION_COUNTS, int)},
            ):
                continue
            if region["as"] not in SECTION_BY_KEY and region["as"] not in REGION_AS:
                v.error(f"{rpath}.as", "unknown value")
            if region["line"] < 1 or any(region[key] < 0 for key in REGION_COUNTS):
                v.error(rpath, "line must be at least 1 and counts must not be negative")
            to = region.get("to")
            if not isinstance(to, dict) or any(k not in SECTION_BY_KEY or not _is(n, int) for k, n in to.items()):
                v.error(f"{rpath}.to", "must map pack sections to counts")
            elif sum(to.values()) != region["extracted"]:
                v.error(f"{rpath}.to", "must add up to extracted")
            if region["kept"] + region["merged"] + region["left_out"] != region["extracted"]:
                v.error(rpath, "kept, merged and left_out must add up to extracted")


def validate(pack: Any) -> list[str]:
    v = _Validator()
    top = {
        "format": str, "schema_version": str, "pack_id": str, "created_at": str, "generator": dict,
        "project": dict, "trust": dict, "privacy": dict, "budget": dict, "coverage": dict, "critical_loss": list,
        "sources": list, "considered_sources": list, "sections": list, "redactions": dict, "warnings": list,
        "integrity": dict,
    }  # fmt: skip
    if not v.obj(pack, "pack", top, {"extraction": dict}):  # extraction: since schema 1.1
        return v.problems
    if pack["format"] != PACK_FORMAT:
        v.error("pack.format", f"must be '{PACK_FORMAT}'")
    version = VERSION.match(pack["schema_version"])
    if not version or version.group(1) != SUPPORTED_MAJOR:
        v.error("pack.schema_version", f"unsupported version (supported: {SUPPORTED_MAJOR}.x)")
    v.match(pack["pack_id"], PACK_ID, "pack.pack_id")
    if isinstance(pack.get("extraction"), dict):
        _validate_extraction(v, pack["extraction"])
    v.match(pack["created_at"], TIMESTAMP, "pack.created_at")
    v.obj(pack["generator"], "pack.generator", {"name": str, "version": str})
    if v.obj(pack["project"], "pack.project", {"name": str, "root_label": str, "vcs": dict}):
        vcs = pack["project"]["vcs"]
        if vcs.get("type") == "git":
            v.obj(vcs, "pack.project.vcs", {"type": str, "branch": str, "head": "str?", "uncommitted_changes": int})
        elif vcs != {"type": "none"}:
            v.error("pack.project.vcs", "must be {'type': 'none'} or a git description")
    if v.obj(pack["trust"], "pack.trust", {"content_is_untrusted_data": bool, "notice": str}):
        if pack["trust"]["content_is_untrusted_data"] is not True:
            v.error("pack.trust.content_is_untrusted_data", "must be true")
    v.obj(pack["privacy"], "pack.privacy", {"redact_pii": bool})

    budget_keys = {
        "max_tokens": int, "estimated_tokens": int, "estimator": str, "hard_budget": bool,
        "exceeded_to_protect_critical": bool, "duplicates_removed": int, "tiers_kept": dict,
        "retention": dict, "dropped": list,
    }  # fmt: skip
    if v.obj(pack["budget"], "pack.budget", budget_keys):
        for key, stats in pack["budget"]["retention"].items():
            if key not in SECTION_BY_KEY:
                v.error(f"pack.budget.retention.{key}", "unknown section")
            v.obj(
                stats, f"pack.budget.retention.{key}", {"extracted": int, "kept": int, "dropped": int, "truncated": int}
            )
        for i, entry in enumerate(pack["budget"]["dropped"]):
            v.obj(entry, f"pack.budget.dropped[{i}]", {"section": str, "items": int})

    if not all(isinstance(label, str) and label for label in pack["considered_sources"]):
        v.error("pack.considered_sources", "must be a list of non-empty strings")
    coverage_keys = {"status": str, "extracted_items": int, "kept_items": int, "dropped_items": dict,
                     "truncated_items": int, "extraction": str, "statement": str}  # fmt: skip
    if v.obj(pack["coverage"], "pack.coverage", coverage_keys):
        coverage = pack["coverage"]
        if coverage["status"] not in COVERAGE_STATUSES:
            v.error("pack.coverage.status", "unknown coverage status")
        if coverage["extraction"] != "selective":
            v.error("pack.coverage.extraction", "must be 'selective'")
        v.obj(
            coverage["dropped_items"], "pack.coverage.dropped_items", {CRITICAL: int, "important": int, "context": int}
        )

    source_ids: set[str] = set()
    for i, source in enumerate(pack["sources"]):
        path = f"pack.sources[{i}]"
        optional = {"kind": str, "sha256": str, "size": int, "ref": str, "created_at": str}
        if v.obj(source, path, {"id": str, "origin": str, "label": str}, optional):
            v.match(source["id"], SOURCE_ID, f"{path}.id")
            if source["id"] in source_ids:
                v.error(f"{path}.id", "is not unique")
            source_ids.add(source["id"])
            if source["origin"] not in ORIGINS:
                v.error(f"{path}.origin", "unknown origin")
            v.match(source.get("sha256"), HEX64, f"{path}.sha256")
            v.match(source.get("created_at"), TIMESTAMP, f"{path}.created_at")

    item_ids: set[str] = set()
    last_index = -1
    for s, section in enumerate(pack["sections"]):
        path = f"pack.sections[{s}]"
        if not v.obj(section, path, {"key": str, "title": str, "tier": str, "items": list}):
            continue
        spec = SECTION_BY_KEY.get(section["key"])
        if spec is None:
            v.error(f"{path}.key", "unknown section")
            continue
        if (section["title"], section["tier"]) != (spec.title, spec.tier):
            v.error(path, "title or tier does not match the section")
        if SECTION_INDEX[spec.key] <= last_index:
            v.error(path, "sections are duplicated or out of order")
        last_index = SECTION_INDEX[spec.key]
        if not section["items"]:
            v.error(f"{path}.items", "must not be empty")
        for i, item in enumerate(section["items"]):
            ipath = f"{path}.items[{i}]"
            required = {"id": str, "text": str, "status": str, "source": str, "extractor": str, "flags": list}
            if not v.obj(item, ipath, required, {"lines": list, "also_in": list}):
                continue
            v.match(item["id"], ITEM_ID, f"{ipath}.id")
            if item["id"] in item_ids:
                v.error(f"{ipath}.id", "is not unique")
            item_ids.add(item["id"])
            v.text(item["text"], f"{ipath}.text")
            if item["status"] not in STATUSES:
                v.error(f"{ipath}.status", f"must be one of {', '.join(STATUSES)}")
            if item["source"] not in source_ids:
                v.error(f"{ipath}.source", "refers to an unknown source")
            if not set(item["flags"]) <= FLAGS or len(set(item["flags"])) != len(item["flags"]):
                v.error(f"{ipath}.flags", "contains unknown or repeated flags")
            if "lines" in item:
                v.lines(item["lines"], f"{ipath}.lines")
            for other in item.get("also_in", []):
                if other not in source_ids or other == item["source"]:
                    v.error(f"{ipath}.also_in", "refers to an unknown or its own source")

    for i, entry in enumerate(pack["critical_loss"]):
        path = f"pack.critical_loss[{i}]"
        if v.obj(entry, path, {"section": str, "reason": str, "source": str, "preview": str}, {"lines": list}):
            spec = SECTION_BY_KEY.get(entry["section"])
            if spec is None or spec.tier != CRITICAL:
                v.error(f"{path}.section", "must be a critical section")
            if entry["reason"] not in LOSS_REASONS:
                v.error(f"{path}.reason", "must be 'dropped' or 'truncated'")
            if entry["source"] not in source_ids:
                v.error(f"{path}.source", "refers to an unknown source")
            if "lines" in entry:
                v.lines(entry["lines"], f"{path}.lines")

    if v.obj(pack["redactions"], "pack.redactions", {"count": int, "by_type": dict}):
        counts = pack["redactions"]["by_type"].values()
        if not all(_is(c, int) and c > 0 for c in counts) or sum(counts) != pack["redactions"]["count"]:
            v.error("pack.redactions", "count does not match by_type")
    for i, warning in enumerate(pack["warnings"]):
        path = f"pack.warnings[{i}]"
        if v.obj(warning, path, {"code": str, "severity": str, "detail": str}, {"source": str}):
            if warning["severity"] not in SEVERITIES:
                v.error(f"{path}.severity", "unknown severity")
            if "source" in warning and warning["source"] not in source_ids:
                v.error(f"{path}.source", "refers to an unknown source")
    integrity = {"algorithm": str, "fingerprint": str, "content_hash": str, "markdown_sha256": str}
    if v.obj(pack["integrity"], "pack.integrity", integrity):
        if pack["integrity"]["algorithm"] != "sha256":
            v.error("pack.integrity.algorithm", "must be 'sha256'")
        for key in ("fingerprint", "content_hash", "markdown_sha256"):
            v.match(pack["integrity"][key], HEX64, f"pack.integrity.{key}")
    return v.problems
