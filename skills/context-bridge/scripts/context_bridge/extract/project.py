"""Extraction from manifests (stack, commands) and from the file list (structure).

Only names and short metadata are taken from manifests: package name, required
runtime, dependency names, scripts and make targets. Values stay untrusted text and
go through the same redaction and injection checks as every other item.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter, defaultdict
from typing import Any

from ..model import FACT, UNCERTAIN, Item

MAX_NAMES = 8
_DEP_SPLIT = re.compile(r"[\s<>=!~;\[(@,]")
_TARGET_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?![=:])")
_GENERIC = {
    "package.swift": "Swift package (Package.swift)",
    "project.yml": "XcodeGen project (project.yml)",
    "gemfile": "Ruby project (Gemfile)",
    "composer.json": "PHP project (composer.json)",
    "pom.xml": "Java project with Maven (pom.xml)",
    "build.gradle": "Gradle build (build.gradle)",
    "build.gradle.kts": "Gradle build (build.gradle.kts)",
    "deno.json": "Deno project (deno.json)",
    "pubspec.yaml": "Dart or Flutter project (pubspec.yaml)",
    "mix.exs": "Elixir project (mix.exs)",
    "setup.cfg": "Python project (setup.cfg)",
    "taskfile.yml": "Task runner configuration (Taskfile.yml)",
}


def _names(values: Any) -> list[str]:
    if isinstance(values, dict):
        return [str(k) for k in values]
    if isinstance(values, list):
        return [_DEP_SPLIT.split(v.strip(), maxsplit=1)[0] for v in values if isinstance(v, str) and v.strip()]
    return []


def _join(names: list[str]) -> str:
    return ", ".join(names[:MAX_NAMES]) + (f" and {len(names) - MAX_NAMES} more" if len(names) > MAX_NAMES else "")


class _Builder:
    def __init__(self, source_id: str, origin_rank: int, name: str) -> None:
        self.source_id, self.origin_rank, self.name = source_id, origin_rank, name
        self.items: list[Item] = []

    def add(
        self, section: str, text: str, extractor: str, lines: tuple[int, int] | None = None, status: str = FACT
    ) -> None:
        self.items.append(
            Item(
                section,
                text,
                status,
                self.source_id,
                extractor,
                lines,
                order=len(self.items),
                origin_rank=self.origin_rank,
            )
        )


def manifest_items(rel: str, text: str, source_id: str, origin_rank: int) -> tuple[list[Item], str | None]:
    """Return (items, project name if the manifest declares one)."""
    name = rel.rsplit("/", 1)[-1]
    lower = name.casefold()
    b = _Builder(source_id, origin_rank, name)
    project_name: str | None = None
    try:
        if lower == "pyproject.toml":
            project = tomllib.loads(text).get("project") or {}
            project_name = project.get("name") if isinstance(project.get("name"), str) else None
            deps = _names(project.get("dependencies"))
            parts = [f"Python project '{project_name}'" if project_name else "Python project"]
            if isinstance(project.get("requires-python"), str):
                parts.append(f"requires Python {project['requires-python']}")
            parts.append(f"dependencies: {_join(deps)}" if deps else "no runtime dependencies")
            b.add("stack", "; ".join(parts), "manifest.pyproject")
            if isinstance(project.get("description"), str):
                b.add("overview", project["description"], "manifest.description")
            for script in _names(project.get("scripts"))[:MAX_NAMES]:
                b.add("commands", f"{script} (console script)", "manifest.pyproject")
        elif lower == "package.json":
            data = json.loads(text)
            project_name = data.get("name") if isinstance(data.get("name"), str) else None
            deps = _names(data.get("dependencies"))
            b.add(
                "stack",
                f"Node.js package '{project_name or name}'; dependencies: {_join(deps) or 'none'}",
                "manifest.package_json",
            )
            if isinstance(data.get("description"), str):
                b.add("overview", data["description"], "manifest.description")
            scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
            for key in list(scripts)[:MAX_NAMES]:
                b.add("commands", f"npm run {key}: {str(scripts[key])[:120]}", "manifest.package_json")
        elif lower == "cargo.toml":
            data = tomllib.loads(text)
            package = data.get("package") or {}
            project_name = package.get("name") if isinstance(package.get("name"), str) else None
            b.add(
                "stack",
                f"Rust crate '{project_name or name}'; "
                f"dependencies: {_join(_names(data.get('dependencies'))) or 'none'}",
                "manifest.cargo",
            )
        elif lower == "go.mod":
            module = next(
                (ln.split()[1] for ln in text.splitlines() if ln.startswith("module ") and len(ln.split()) > 1), None
            )
            version = next(
                (ln.split()[1] for ln in text.splitlines() if ln.startswith("go ") and len(ln.split()) > 1), None
            )
            b.add("stack", f"Go module '{module or '?'}'" + (f", Go {version}" if version else ""), "manifest.go_mod")
        elif lower.startswith("requirements") and lower.endswith(".txt"):
            reqs = _names([ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "-"))])
            b.add("stack", f"Python requirements ({name}): {_join(reqs) or 'none'}", "manifest.requirements")
        elif lower in ("makefile", "justfile"):
            tool = "make" if lower == "makefile" else "just"
            seen: list[str] = []
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = _TARGET_RE.match(line)
                if m and not m.group(1).startswith(".") and m.group(1) not in seen and len(seen) < MAX_NAMES:
                    seen.append(m.group(1))
                    b.add("commands", f"{tool} {m.group(1)}", f"manifest.{lower}", (lineno, lineno))
        elif lower in _GENERIC:
            b.add("stack", _GENERIC[lower], "manifest.detected")
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError):
        b.items = []
        b.add("stack", f"{name} is present but could not be parsed", "manifest.unparsed", status=UNCERTAIN)
    return b.items, project_name


def structure_items(paths: list[str], source_id: str) -> list[Item]:
    """Summarise the file list: files per top-level directory and the top-level files."""
    by_dir: dict[str, list[str]] = defaultdict(list)
    top_files: list[str] = []
    for path in paths:
        if "/" in path:
            by_dir[path.split("/", 1)[0]].append(path)
        else:
            top_files.append(path)
    items: list[Item] = []
    for directory, files in sorted(by_dir.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        exts = Counter(
            (f.rsplit(".", 1)[-1].casefold() if "." in f.rsplit("/", 1)[-1] else "no extension") for f in files
        )
        summary = ", ".join(f"{ext} {count}" for ext, count in exts.most_common(3))
        items.append(
            Item(
                "structure",
                f"{directory}/: {len(files)} {'file' if len(files) == 1 else 'files'} ({summary})",
                FACT,
                source_id,
                "structure.directory",
                order=len(items),
                origin_rank=5,
            )
        )
    if top_files:
        names = sorted(top_files)
        text = "Top-level files: " + ", ".join(names[:12]) + (f" and {len(names) - 12} more" if len(names) > 12 else "")
        items.insert(0, Item("structure", text, FACT, source_id, "structure.top_level", order=-1, origin_rank=5))
    return items


def changelog_items(text: str, source_id: str, origin_rank: int) -> list[Item]:
    """Bullets of the newest version section (the first ``## `` heading) as state items."""
    items: list[Item] = []
    heading: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            if heading is not None:
                break
            heading = line[3:].strip()
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*\S)", line)
        if heading and bullet and len(items) < 5:
            items.append(
                Item(
                    "state",
                    f"Changelog {heading}: {bullet.group(1)}",
                    FACT,
                    source_id,
                    "changelog.latest",
                    (lineno, lineno),
                    order=len(items),
                    origin_rank=origin_rank,
                )
            )
    return items
