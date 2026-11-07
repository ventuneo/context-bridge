#!/usr/bin/env python3
"""First retention metrics: how much important information survives compression.

A reference case lives in ``quality/cases/<name>/``:

* ``project/``      synthetic project files
* ``handoff.json``  session handoff
* ``expected.json`` ground truth: items that must be kept (with category, criticality,
                    matching terms and optionally the expected status) and forbidden
                    content that must never appear in a pack

Placeholders ``{{FAKE_GITHUB_TOKEN}}`` and ``{{FAKE_EMAIL}}`` are replaced at runtime,
so the repository never contains secret-looking strings. Noise (source files, a
``.env`` file) is generated from ``expected.json["noise"]``. Packs are built with
``dry_run=True`` in a temporary copy: nothing is written anywhere.

Score: 100 × Σ(weight × found) / Σ weight with weights critical 3, important 2,
normal 1. Matching is lexical (normalised terms), which suits an extractive packer.

Usage: ``python3 -I quality/evaluate.py`` prints a table for every case and budget.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "cases"
sys.path.insert(0, str(REPO / "skills" / "context-bridge" / "scripts"))

from context_bridge import pack as pack_mod  # noqa: E402
from context_bridge import scan as scan_mod  # noqa: E402
from context_bridge.budget import normalise  # noqa: E402

WEIGHTS = {"critical": 3, "important": 2, "normal": 1}
PLACEHOLDERS = {
    "{{FAKE_GITHUB_TOKEN}}": "gh" + "p_" + ("Harbor0Ledger1Fake2Token3Value4" + "Abcdefghij")[:36],
    "{{FAKE_EMAIL}}": "inspector.one" + "@" + "harbour-mail.ch",
}
BUDGETS = (600, 1000, 2000)


def substitute(text: str) -> str:
    for placeholder, value in PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    return text


def load_case(case_dir: Path) -> tuple[dict[str, Any], bytes]:
    expected = json.loads(substitute((case_dir / "expected.json").read_text(encoding="utf-8")))
    handoff = substitute((case_dir / "handoff.json").read_text(encoding="utf-8")).encode("utf-8")
    return expected, handoff


def prepare(case_dir: Path, workdir: Path, expected: dict[str, Any]) -> Path:
    root = workdir / case_dir.name
    shutil.copytree(case_dir / "project", root)
    for path in root.rglob("*"):
        if path.is_file():
            path.write_text(substitute(path.read_text(encoding="utf-8")), encoding="utf-8")
    noise = expected.get("noise", {})
    for d in range(noise.get("source_dirs", 0)):
        for f in range(noise.get("files_per_dir", 0)):
            target = root / "src" / f"module_{d:02d}" / f"part_{f}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"print('noise {d} {f}')\n", encoding="utf-8")
    if noise.get("env_secret"):
        (root / ".env").write_text(noise["env_secret"] + "\n", encoding="utf-8")
    return root


def evaluate(result: pack_mod.PackResult, expected: dict[str, Any], source_tokens: int) -> dict[str, Any]:
    kept = [(normalise(i["text"]), i["status"]) for s in result.pack["sections"] for i in s["items"]]
    blob = normalise(json.dumps(result.pack, ensure_ascii=False) + "\n" + result.markdown)
    total = gained = 0
    by_category: dict[str, list[int]] = {}
    status_checked = status_ok = 0
    missing: list[str] = []
    for item in expected["items"]:
        terms = [normalise(t) for t in item["all"]]
        match = next((status for text, status in kept if all(t in text for t in terms)), None)
        weight = WEIGHTS[item["criticality"]]
        total += weight
        found = match is not None
        gained += weight if found else 0
        counts = by_category.setdefault(item["category"], [0, 0])
        counts[0] += int(found)
        counts[1] += 1
        if not found:
            missing.append(item["id"])
        if found and "status" in item:
            status_checked += 1
            status_ok += int(match == item["status"])
    critical = [i for i in expected["items"] if i["criticality"] == "critical"]
    critical_found = sum(1 for i in critical if i["id"] not in missing)
    forbidden = [f["id"] for f in expected["forbidden"] if any(normalise(t) in blob for t in f["any"])]
    tokens = result.pack["budget"]["estimated_tokens"]
    return {
        "score": round(100 * gained / total, 1),
        "critical_recall": critical_found / len(critical),
        "recall_by_category": {k: round(v[0] / v[1], 3) for k, v in sorted(by_category.items())},
        "status_accuracy": round(status_ok / status_checked, 3) if status_checked else None,
        "missing": missing,
        "forbidden_hits": forbidden,
        "tokens": tokens,
        "source_tokens": source_tokens,
        "compression": round(tokens / source_tokens, 3) if source_tokens else None,
        "exit_code": result.exit_code,
        "critical_loss_reported": bool(result.pack["critical_loss"]),
    }


def run_case(case_dir: Path, budget: int, hard_budget: bool = False) -> dict[str, Any]:
    expected, handoff = load_case(case_dir)
    with tempfile.TemporaryDirectory(prefix="cb-quality-") as tmp:
        root = prepare(case_dir, Path(tmp), expected)
        source_tokens = scan_mod.scan(root).totals()["estimated_tokens"]
        result = pack_mod.build(
            root, handoff=handoff, approve=True, dry_run=True, budget=budget, hard_budget=hard_budget
        )
        return evaluate(result, expected, source_tokens)


def main() -> int:
    print(f"{'case':<10} {'budget':>6} {'mode':<5} {'score':>6} {'critical':>8} {'status':>6} "
          f"{'tokens':>6} {'ratio':>6} {'exit':>4}  missing / forbidden")  # fmt: skip
    for case_dir in sorted(p for p in CASES.iterdir() if (p / "expected.json").is_file()):
        for budget in BUDGETS:
            for hard in (False, True):
                m = run_case(case_dir, budget, hard)
                print(f"{case_dir.name:<10} {budget:>6} {'hard' if hard else 'soft':<5} {m['score']:>6} "
                      f"{m['critical_recall']:>8.0%} {m['status_accuracy'] or 0:>6.0%} {m['tokens']:>6} "
                      f"{m['compression']:>6} {m['exit_code']:>4}  {','.join(m['missing']) or '-'} / "
                      f"{','.join(m['forbidden_hits']) or '-'}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
