"""Build the token calibration samples from the synthetic reference cases.

The samples are committed together with their measured token counts in
``measurements.json``. Rebuild them only right before measuring again: a changed
renderer changes the samples, and the old measurements would no longer belong to them.

    python3 -I quality/tokens/make_samples.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "skills" / "context-bridge" / "scripts"))
sys.path.insert(0, str(REPO / "quality"))

import evaluate  # noqa: E402

from context_bridge import autoresume, pack, resume  # noqa: E402

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
# Source files exactly as stored in the repository (placeholders for fake secrets stay placeholders).
# The files named text-*.md are written by hand and are not touched here.
RAW = {
    "en-basic-docs.md": ("basic", ["README.md", "CLAUDE.md", "docs/setup.md", "docs/roadmap.md", "CHANGELOG.md"]),
    "en-conflicts.md": ("conflicts", ["README.md", "notes.md", "docs/decisions/0001-postgres.md",
                                      "docs/decisions/0002-sqlite.md"]),
    "en-large-docs.md": ("large", ["README.md", "AGENTS.md", "CLAUDE.md", "docs/operations.md",
                                   "docs/assumptions.md", "docs/glossary.md"]),
    "de-german.md": ("german", ["README.md", "CLAUDE.md", "notizen.md", "docs/entscheidungen/0001-datenbank.md"]),
    "manifests.txt": ("large", ["pyproject.toml", "package.json", "Makefile"]),
}  # fmt: skip
PACKS = (("basic", 2000), ("german", 2000), ("conflicts", 2000), ("injection", 2000), ("large", 1000))


def main() -> int:
    out = HERE / "samples"
    out.mkdir(exist_ok=True)
    samples: dict[str, str] = {}
    for name, (case, files) in RAW.items():
        base = evaluate.CASES / case / "project"
        samples[name] = "\n\n".join((base / f).read_text(encoding="utf-8").strip() for f in files) + "\n"
    with tempfile.TemporaryDirectory() as tmp, evaluate.isolated_runtime(Path(tmp)):
        for case, budget in PACKS:  # rendered packs, a resume output and a hook digest
            expected, handoff = evaluate.load_case(evaluate.CASES / case)
            root = evaluate.prepare(evaluate.CASES / case, Path(tmp), expected)
            result = pack.build(root, handoff=handoff, approve=True, budget=budget, now=NOW)
            samples[f"pack-{case}.md"] = result.markdown
            if case == "basic":
                samples["resume-basic.txt"] = resume.resume(root, now=NOW)[1] or ""
            if case == "large":
                samples["en-guide.md"] = (root / "docs" / "guides" / "guide-01.md").read_text(encoding="utf-8")
                samples["digest-large.txt"] = autoresume.digest(json.dumps({"cwd": str(root)}).encode(), now=NOW)
    for name, text in sorted(samples.items()):
        (out / name).write_text(text, encoding="utf-8")
        print(f"{name:20} {len(text):6} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
