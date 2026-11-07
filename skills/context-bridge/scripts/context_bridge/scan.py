"""scan: decide which project files may be used, and report why others may not.

Guarantees:

* scan writes nothing, anywhere.
* Deny roots are checked before anything inside the project is read.
* Only allowlisted files are opened, and only to measure them and to look for
  secrets, personal data, prompt-injection patterns and invisible characters.
* Reports never contain file contents or matched values, only types and line numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import gitrun, injection, policy, redact, safepath
from .config import Config, load_config
from .errors import EXIT_OK, EXIT_WARNINGS, PolicyViolation, UnsafePathError

REPORT_FORMAT = "context-bridge.scan"
REPORT_VERSION = "1.0"
MAX_PATHS_PER_REASON = 50

# Exclusion reasons added by scan (in addition to policy.* and safepath.* reasons).
BINARY = "binary"
TOTAL_LIMIT = "total_limit"
CONTAINS_PRIVATE_KEY = "contains_private_key"
EXTERNAL_NOT_ALLOWED = "external_not_allowed"
SYMLINKED_DIRECTORY = "symlinked_directory"

# Exclusions that point at something suspicious and therefore count as warnings.
SECURITY_REASONS = frozenset(
    {
        safepath.SYMLINK_OUTSIDE_ROOT,
        safepath.CHANGED_DURING_READ,
        CONTAINS_PRIVATE_KEY,
        EXTERNAL_NOT_ALLOWED,
        policy.DENY_ROOT,
    }
)


@dataclass
class IncludedFile:
    path: str
    kind: str
    origin: str  # "project" or "external"
    size: int
    sha256: str
    estimated_tokens: int
    valid_utf8: bool
    via_symlink: bool
    secrets: list[dict[str, Any]] = field(default_factory=list)
    personal_data: list[dict[str, Any]] = field(default_factory=list)
    injection: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ScanReport:
    root_label: str
    vcs: str
    config: dict[str, Any]
    included: list[IncludedFile] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def exclude(self, reason: str, path: str) -> None:
        self.excluded.setdefault(reason, []).append(path)

    def finalise(self) -> None:
        """Sort for deterministic output."""
        for paths in self.excluded.values():
            paths.sort()

    @property
    def has_warnings(self) -> bool:
        findings = any(f.secrets or f.personal_data or f.injection for f in self.included)
        return bool(findings or self.warnings or SECURITY_REASONS.intersection(self.excluded))

    def totals(self) -> dict[str, int]:
        return {
            "included_files": len(self.included),
            "included_bytes": sum(f.size for f in self.included),
            "estimated_tokens": sum(f.estimated_tokens for f in self.included),
            "excluded_entries": sum(len(v) for v in self.excluded.values()),
            "secret_findings": sum(len(f.secrets) for f in self.included),
            "personal_data_findings": sum(len(f.personal_data) for f in self.included),
            "injection_findings": sum(len(f.injection) for f in self.included),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": REPORT_FORMAT,
            "version": REPORT_VERSION,
            "root": self.root_label,
            "vcs": self.vcs,
            "wrote_nothing": True,
            "config": self.config,
            "totals": self.totals(),
            "included": [asdict(f) for f in self.included],
            "excluded": {
                reason: {
                    "count": len(paths),
                    "paths": paths[:MAX_PATHS_PER_REASON],
                    "truncated": len(paths) > MAX_PATHS_PER_REASON,
                }
                for reason, paths in sorted(self.excluded.items())
            },
            "warnings": self.warnings,
        }


def estimate_tokens(text: str) -> int:
    """Rough token estimate (characters / 4); a tokenizer is not in the standard library."""
    return math.ceil(len(text) / 4)


def _walk(root: Path, deny: policy.DenyRoots, report: ScanReport) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        keep: list[str] = []
        for name in sorted(dirnames):
            full = Path(dirpath, name)
            reason = policy.dir_exclusion(name)
            if full.is_symlink():
                report.exclude(SYMLINKED_DIRECTORY, f"{prefix}{name}/")
            elif reason:
                report.exclude(reason, f"{prefix}{name}/")
            elif deny and deny.is_deny_root(full):
                report.exclude(policy.DENY_ROOT, f"{prefix}{name}/")
            else:
                keep.append(name)
        dirnames[:] = keep
        files.extend(prefix + name for name in sorted(filenames))
    return files


def _denied_by_parent(root: Path, rel: str, deny: policy.DenyRoots, cache: dict[str, bool]) -> bool:
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        directory = "/".join(parts[:i])
        if directory not in cache:
            cache[directory] = deny.is_deny_root(root / directory)
        if cache[directory]:
            return True
    return False


def _analyse(text: str, cfg: Config) -> tuple[str, list[dict], list[dict], list[dict]]:
    clean, invisible = injection.strip_invisible(text)
    findings = redact.find(clean, pii=cfg.redact_pii)
    secrets = [f.to_dict() for f in findings if f.kind == redact.SECRET]
    personal = [f.to_dict() for f in findings if f.kind == redact.PII]
    flagged = [f.to_dict() for f in invisible + injection.detect(clean)]
    return clean, secrets, personal, flagged


def _read_and_add(
    report: ScanReport, cfg: Config, base: Path, rel: str, label: str, kind: str, origin: str, total: list[int]
) -> None:
    try:
        content = safepath.read_file(base, rel, cfg.max_file_bytes)
    except UnsafePathError as exc:
        report.exclude(exc.reason, label)
        return
    if safepath.is_binary(content.data):
        report.exclude(BINARY, label)
        return
    if total[0] + content.size > cfg.max_total_bytes:
        report.exclude(TOTAL_LIMIT, label)
        return
    text, valid = safepath.decode_text(content.data)
    if redact.contains_private_key(text):
        report.exclude(CONTAINS_PRIVATE_KEY, label)
        return
    clean, secrets, personal, flagged = _analyse(text, cfg)
    total[0] += content.size
    report.included.append(
        IncludedFile(
            path=label,
            kind=kind,
            origin=origin,
            size=content.size,
            sha256=content.sha256,
            estimated_tokens=estimate_tokens(clean),
            valid_utf8=valid,
            via_symlink=content.via_symlink,
            secrets=secrets,
            personal_data=personal,
            injection=flagged,
        )
    )


def _display_external(path: Path) -> str:
    home = Path(os.path.expanduser("~")).resolve()
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return path.name


def _scan_external(report: ScanReport, cfg: Config, root: Path, deny: policy.DenyRoots, total: list[int]) -> None:
    allowed = [Path(os.path.realpath(p)) for p in cfg.allowed_external_roots]
    for requested in cfg.external_sources:
        candidate = requested if requested.is_absolute() else root / requested
        resolved = Path(os.path.realpath(candidate))
        label = _display_external(resolved)
        base = next((a for a in allowed if safepath.is_within(resolved, a)), None)
        if base is None:
            report.exclude(EXTERNAL_NOT_ALLOWED, label)
            continue
        if deny.blocks(candidate):
            report.exclude(policy.DENY_ROOT, label)
            continue
        rel = resolved.relative_to(base).as_posix()
        decision = policy.classify(rel, include=(("**", "external_note"),))
        if not decision.included:
            report.exclude(decision.reason or policy.NOT_IN_ALLOWLIST, label)
            continue
        _read_and_add(report, cfg, base, rel, label, "external_note", "external", total)


def scan(root_arg: str | os.PathLike[str], user_config_path: Path | None = None) -> ScanReport:
    root = safepath.resolve_root(root_arg)
    user_only = load_config(root, user_config_path, include_project=False)
    deny = user_only.deny()
    if deny.blocks(root):
        raise PolicyViolation("the project root lies inside a denied location (privacy.deny_roots); nothing was read")

    cfg = load_config(root, user_config_path)
    report = ScanReport(
        root_label=root.name or str(root),
        vcs="none",
        config={
            "user_config": cfg.user_config_path is not None,
            "project_config": cfg.project_config_loaded,
            "max_file_bytes": cfg.max_file_bytes,
            "max_total_bytes": cfg.max_total_bytes,
            "redact_pii": cfg.redact_pii,
            "deny_roots": len(cfg.deny_roots),
        },
    )
    report.warnings.extend({"code": "config_warning", "detail": w} for w in cfg.warnings)

    status = gitrun.inspect(root)
    candidates: list[str] | None = None
    if status.usable:
        try:
            candidates = gitrun.list_files(root)
            report.vcs = "git"
        except gitrun.GitError:
            report.warnings.append({"code": gitrun.GIT_FAILED, "detail": "git ls-files failed, used a directory walk"})
    elif status.reason == gitrun.UNTRUSTED_CONFIG:
        report.warnings.append({"code": gitrun.UNTRUSTED_CONFIG, "detail": ", ".join(status.untrusted_keys)})
        report.vcs = gitrun.UNTRUSTED_CONFIG
    if candidates is None:
        candidates = _walk(root, deny, report)
        if report.vcs == "none" and status.is_repo:
            report.vcs = "git-not-used"

    allowlisted: list[tuple[str, str]] = []
    deny_cache: dict[str, bool] = {}
    for rel in candidates:
        if deny and _denied_by_parent(root, rel, deny, deny_cache):
            report.exclude(policy.DENY_ROOT, rel)
            continue
        decision = policy.classify(rel, cfg.include, cfg.exclude)
        if decision.included and decision.kind:
            allowlisted.append((rel, decision.kind))
        else:
            report.exclude(decision.reason or policy.NOT_IN_ALLOWLIST, rel)

    total = [0]
    allowlisted.sort(key=lambda item: (policy.KIND_PRIORITY.get(item[1], 99), item[0].count("/"), item[0]))
    for rel, kind in allowlisted:
        _read_and_add(report, cfg, root, rel, rel, kind, "project", total)
    _scan_external(report, cfg, root, deny, total)
    report.finalise()
    return report


# ---------------------------------------------------------------------------
# Output


def _safe(text: str) -> str:
    """Neutralise control characters (e.g. ANSI escapes in hostile file names)."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB"


def format_text(report: ScanReport) -> str:
    totals = report.totals()
    lines = [f"Context Bridge scan: {_safe(report.root_label)} ({report.vcs})", "Nothing was written.", ""]
    lines.append(
        f"Included: {totals['included_files']} files, {_kb(totals['included_bytes'])}, "
        f"~{totals['estimated_tokens']} tokens"
    )
    width = max((len(_safe(f.path)) for f in report.included), default=10)
    for item in report.included:
        notes = [f"secret: {s['type']} (line {s['line']})" for s in item.secrets]
        notes += [f"personal data: {p['type']} (line {p['line']})" for p in item.personal_data]
        notes += [f"injection: {i['type']} (line {i['line']})" for i in item.injection]
        suffix = ("   ! " + "; ".join(notes)) if notes else ""
        lines.append(
            f"  {_safe(item.path):<{width}}  {item.kind:<13} {_kb(item.size):>9}  ~{item.estimated_tokens} tok{suffix}"
        )
    lines.append("")
    lines.append(f"Excluded: {totals['excluded_entries']} entries")
    for reason, paths in sorted(report.excluded.items()):
        sample = ", ".join(_safe(p) for p in paths[:4]) + (", ..." if len(paths) > 4 else "")
        lines.append(f"  {reason:<22} {len(paths):>5}   {sample}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {w['code']}: {_safe(str(w.get('detail', '')))}" for w in report.warnings)
    lines.append("")
    lines.append(
        f"Findings: {totals['secret_findings']} secrets, {totals['personal_data_findings']} personal data, "
        f"{totals['injection_findings']} injection patterns. Values are never shown; pack will redact them."
    )
    return "\n".join(lines)


def run_cli(args: argparse.Namespace) -> int:
    report = scan(args.root)
    if args.json:
        json.dump(report.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(format_text(report))
    return EXIT_WARNINGS if report.has_warnings else EXIT_OK
