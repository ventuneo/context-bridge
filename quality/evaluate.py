#!/usr/bin/env python3
"""Context Quality Score (CQS): measured retention of important information.

A reference case lives in ``quality/cases/<name>/``:

* ``project/``      synthetic project files (no real data)
* ``handoff.json``  session handoff
* ``expected.json`` ground truth and settings:
  - ``items``: what must survive. Each has an ``id``, a ``category`` (goal, constraint,
    decision, next_step, fact, assumption, open_question), a ``criticality``
    (critical 3 points, important 2, normal 1), matching terms ``all`` (every term must
    occur in one pack item, compared after Unicode and case normalisation), and
    optionally the expected ``status``, ``origin`` (``file`` or ``session``), ``source``
    (file label), ``flags`` and ``also_in_session``.
  - ``forbidden``: content that must never appear anywhere in a pack.
  - ``noise``: generated files (code, guide documents, a ``.env`` secret).
  - ``gates``: ``reference_budget``, ``min_score``, ``max_compression``.

Placeholders such as ``{{FAKE_GITHUB_TOKEN}}`` are replaced at runtime, so the
repository never contains secret-looking strings.

Every number is counted, not estimated:

* CQS = 100 × points found / points possible (weights above)
* critical recall, recall per category and per criticality, with the missing ids
* status accuracy (fact / assumption / uncertain), provenance accuracy (file-backed vs.
  unverifiable session note), flag accuracy (redacted, instruction_like, unlabeled)
* forbidden hits, pack tokens, tokens read from the sources, compression ratio,
  points per 1000 pack tokens
* whether a critical loss was reported by ``pack`` (exit 3) and by ``verify``

Packs are written into temporary copies with an isolated configuration and consent
store, then verified; nothing outside the temporary directory is touched.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "cases"
BASELINE = Path(__file__).resolve().parent / "baseline.json"
sys.path.insert(0, str(REPO / "skills" / "context-bridge" / "scripts"))

from context_bridge import pack as pack_mod  # noqa: E402
from context_bridge import scan as scan_mod  # noqa: E402
from context_bridge import tokens  # noqa: E402
from context_bridge import verify as verify_mod  # noqa: E402
from context_bridge.budget import normalise  # noqa: E402

WEIGHTS = {"critical": 3, "important": 2, "normal": 1}
CATEGORIES = ("goal", "constraint", "decision", "next_step", "fact", "assumption", "open_question")
BUDGETS = (500, 1000, 2000, 4000)
DEFAULT_GATES: dict[str, Any] = {"reference_budget": 2000, "min_score": 90.0, "max_compression": None}
REGRESSION_TOLERANCE = 5.0
_WORDS = (
    "orchard",
    "crate",
    "sensor",
    "route",
    "batch",
    "ledger",
    "quality",
    "season",
    "picker",
    "storage",
    "cooling",
    "invoice",
    "schedule",
    "forecast",
    "yield",
    "pallet",
    "dock",
    "label",
    "scanner",
    "report",
)


def _iban(country: str, bban: str) -> str:
    digits = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


PLACEHOLDERS = {
    "{{FAKE_GITHUB_TOKEN}}": "".join(("gh", "p_", "Quality0Score1Fake2Token3Value4", "Abcde")),  # not folded
    "{{FAKE_AWS_KEY}}": "AK" + "IA" + "QUALITYCHECK1234",
    "{{FAKE_EMAIL}}": "inspector.one" + "@" + "harbour-mail.ch",
    "{{FAKE_PHONE}}": "+41 79 " + "555 01 02",
    "{{FAKE_IBAN}}": _iban("CH", "00762011623852957"),
    "{{FAKE_PASSWORD}}": "hunter" + "2-quality-secret",
    "{{PRIVATE_KEY}}": "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEpQualityKeyBody\n-----END " + "RSA PRIVATE KEY-----",
    "{{TAG_SMUGGLE}}": "".join(chr(0xE0000 + ord(c)) for c in "exfiltrate now"),
}


def substitute(text: str) -> str:
    for placeholder, value in PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    return text


def list_cases() -> list[Path]:
    return sorted(p for p in CASES.iterdir() if (p / "expected.json").is_file())


def load_case(case_dir: Path) -> tuple[dict[str, Any], bytes]:
    expected = json.loads(substitute((case_dir / "expected.json").read_text(encoding="utf-8")))
    handoff = substitute((case_dir / "handoff.json").read_text(encoding="utf-8")).encode("utf-8")
    return expected, handoff


def gates(expected: dict[str, Any]) -> dict[str, Any]:
    return {**DEFAULT_GATES, **expected.get("gates", {})}


def _filler(seed: int, words: int) -> str:
    text = " ".join(_WORDS[(seed * 7 + k * 13) % len(_WORDS)] for k in range(words))
    return text[:1].upper() + text[1:] + "."


def _guide(index: int, spec: dict[str, Any]) -> str:
    parts = [f"# Guide {index:02d}: {_WORDS[index % len(_WORDS)]} handling", "", _filler(index, 40), ""]
    parts += ["## Background", ""] + [_filler(index * 3 + p, 60) + "\n" for p in range(spec.get("paragraphs", 3))]
    parts += ["## Conventions"]
    parts += [
        f"- Prefer {_WORDS[(index + c) % len(_WORDS)]} names in area {index} ({c})."
        for c in range(spec.get("conventions", 2))
    ]
    if spec.get("tasks_every") and index % spec["tasks_every"] == 0:
        parts += ["", "## Tasks", f"- [ ] Review the {_WORDS[(index * 5) % len(_WORDS)]} checklist for area {index}."]
    parts += ["", "## Troubleshooting", "", _filler(index * 11, 50), ""]
    return "\n".join(parts) + "\n"


def prepare(case_dir: Path, workdir: Path, expected: dict[str, Any]) -> Path:
    root = workdir / case_dir.name
    shutil.copytree(case_dir / "project", root)
    for path in root.rglob("*"):
        if path.is_file():
            path.write_text(substitute(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    noise = expected.get("noise", {})
    for d in range(noise.get("source_dirs", 0)):
        for f in range(noise.get("files_per_dir", 0)):
            target = root / "src" / f"module_{d:02d}" / f"part_{f}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"print('noise {d} {f}')\n", encoding="utf-8", newline="\n")
    docs = noise.get("docs")
    if docs:
        folder = root / docs.get("dir", "docs/guides")
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(docs["count"]):
            (folder / f"guide-{i:02d}.md").write_text(_guide(i, docs), encoding="utf-8", newline="\n")
    if noise.get("env_secret"):
        (root / ".env").write_text(noise["env_secret"] + "\n", encoding="utf-8", newline="\n")
    return root


@contextlib.contextmanager
def isolated_runtime(tmp: Path) -> Iterator[None]:
    """Default configuration and a private consent store for reproducible runs."""
    keys = ("CONTEXT_BRIDGE_CONFIG", "XDG_STATE_HOME")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["CONTEXT_BRIDGE_CONFIG"] = str(tmp / "no-user-config.toml")
    os.environ["XDG_STATE_HOME"] = str(tmp / "state")
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _project_files(root: Path) -> int:
    return sum(len(files) for path, _dirs, files in os.walk(root) if ".context-bridge" not in Path(path).parts)


def evaluate(pack: dict[str, Any], markdown: str, expected: dict[str, Any]) -> dict[str, Any]:
    sources = {s["id"]: s for s in pack["sources"]}
    kept = [(normalise(i["text"]), i) for s in pack["sections"] for i in s["items"]]
    blob = normalise(json.dumps(pack, ensure_ascii=False) + "\n" + markdown)
    points = max_points = 0
    by_category: dict[str, list[int]] = {}
    by_criticality: dict[str, list[int]] = {}
    checks: dict[str, dict[str, Any]] = {
        k: {"checked": 0, "correct": 0, "mismatches": []} for k in ("status", "provenance", "flags")
    }
    verdicts = []
    for exp in expected["items"]:
        terms = [normalise(t) for t in exp["all"]]
        match = next((item for text, item in kept if all(t in text for t in terms)), None)
        weight = WEIGHTS[exp["criticality"]]
        max_points += weight
        points += weight if match else 0
        for table, key in ((by_category, exp["category"]), (by_criticality, exp["criticality"])):
            table.setdefault(key, [0, 0])
            table[key][0] += int(match is not None)
            table[key][1] += 1
        verdict: dict[str, Any] = {
            "id": exp["id"],
            "criticality": exp["criticality"],
            "category": exp["category"],
            "found": match is not None,
            "item": match["id"] if match else None,
        }
        if match:
            source = sources[match["source"]]
            actual_origin = "session" if source["origin"] == "session" else "file"
            observed = {
                "status": (exp.get("status"), match["status"]),
                "provenance": (
                    (exp.get("origin"), exp.get("source"), exp.get("also_in_session")),
                    (
                        actual_origin,
                        source["label"] if exp.get("source") else None,
                        any(sources[s]["origin"] == "session" for s in match.get("also_in", []))
                        if exp.get("also_in_session") is not None
                        else None,
                    ),
                ),
                "flags": (exp.get("flags"), match["flags"]),
            }
            for key, (want, got) in observed.items():
                if key == "provenance" and want == (None, None, None):
                    continue
                if key != "provenance" and want is None:
                    continue
                ok = set(want) <= set(got) if key == "flags" else want == got
                checks[key]["checked"] += 1
                checks[key]["correct"] += int(ok)
                verdict[f"{key}_ok"] = ok
                if not ok:
                    checks[key]["mismatches"].append({"id": exp["id"], "expected": want, "actual": got})
        verdicts.append(verdict)
    critical = by_criticality.get("critical", [0, 0])
    missing = [v["id"] for v in verdicts if not v["found"]]
    tokens = pack["budget"]["estimated_tokens"]
    return {
        "score": round(100 * points / max_points, 1) if max_points else 0.0,
        "points": points,
        "max_points": max_points,
        "critical_found": critical[0],
        "critical_total": critical[1],
        "critical_missing": [v["id"] for v in verdicts if not v["found"] and v["criticality"] == "critical"],
        "missing": missing,
        "by_category": {k: by_category[k] for k in CATEGORIES if k in by_category},
        "by_criticality": by_criticality,
        **{
            f"{k}_accuracy": (round(c["correct"] / c["checked"], 3) if c["checked"] else None)
            for k, c in checks.items()
        },
        "mismatches": {k: c["mismatches"] for k, c in checks.items() if c["mismatches"]},
        "forbidden_hits": [
            f["id"] for f in expected.get("forbidden", []) if any(normalise(t) in blob for t in f["any"])
        ],
        "tokens": tokens,
        "points_per_1k_tokens": round(points / tokens * 1000, 1) if tokens else None,
        "loss_reported": bool(pack["critical_loss"]),
        "coverage": pack["coverage"]["status"],
        "warnings": [w["code"] for w in pack["warnings"]],
        "items": verdicts,
    }


def run_case(case_dir: Path, budget: int, hard_budget: bool = False) -> dict[str, Any]:
    expected, handoff = load_case(case_dir)
    with tempfile.TemporaryDirectory(prefix="cb-quality-") as tmp, isolated_runtime(Path(tmp)):
        root = prepare(case_dir, Path(tmp), expected)
        source_tokens = scan_mod.scan(root).totals()["estimated_tokens"]
        result = pack_mod.build(root, handoff=handoff, approve=True, budget=budget, hard_budget=hard_budget)
        report = verify_mod.verify(root)
        metrics = evaluate(result.pack, result.markdown, expected)
        metrics.update(
            case=case_dir.name,
            budget=budget,
            mode="hard" if hard_budget else "soft",
            project_files=_project_files(root),
            source_tokens=source_tokens,
            compression=round(metrics["tokens"] / source_tokens, 3) if source_tokens else None,
            pack_exit=result.exit_code,
            verify_exit=report.exit_code,
            verify_errors=[f.code for f in report.errors],
        )
    return metrics


def run_matrix(cases: list[Path] | None = None, budgets: tuple[int, ...] = BUDGETS) -> list[dict[str, Any]]:
    return [run_case(c, b, hard) for c in (cases or list_cases()) for b in budgets for hard in (False, True)]


def check_gates(results: list[dict[str, Any]]) -> list[str]:
    """Hard quality gates. Returns human-readable failures (empty list: all gates pass)."""
    failures: list[str] = []
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r)
        run = f"{r['case']} {r['budget']} {r['mode']}"
        if r["forbidden_hits"]:
            failures.append(f"{run}: forbidden content in the pack: {', '.join(r['forbidden_hits'])}")
        if r["verify_errors"]:
            failures.append(f"{run}: verify reports errors on a genuine pack: {', '.join(r['verify_errors'])}")
        if r["mode"] == "soft" and r["critical_missing"]:
            failures.append(f"{run}: CRITICAL LOSS without --hard-budget: {', '.join(r['critical_missing'])}")
        if r["missing"] and r["coverage"] == "all_extracted_items_kept":
            failures.append(f"{run}: the pack claims to keep every item although {', '.join(r['missing'])} are missing")
        if r["critical_missing"] and r["coverage"] != "critical_loss":
            failures.append(
                f"{run}: critical items {', '.join(r['critical_missing'])} are missing but coverage is {r['coverage']}"
            )
        if r["critical_missing"] and not (r["loss_reported"] and r["pack_exit"] == 3 and r["verify_exit"] == 3):
            failures.append(f"{run}: critical loss {', '.join(r['critical_missing'])} was not reported clearly")
    for case, runs in by_case.items():
        g = gates(load_case(CASES / case)[0])
        ref = next((r for r in runs if r["budget"] == g["reference_budget"] and r["mode"] == "soft"), None)
        if ref is None:
            continue
        if ref["score"] < g["min_score"]:
            failures.append(
                f"{case}: CQS {ref['score']} at the reference budget {g['reference_budget']} is below {g['min_score']}"
            )
        for key in ("status_accuracy", "provenance_accuracy", "flags_accuracy"):
            if ref[key] is not None and ref[key] < 1.0:
                failures.append(f"{case}: {key} {ref[key]} at the reference budget (mismatches: {ref['mismatches']})")
        if g["max_compression"] is not None and ref["compression"] > g["max_compression"]:
            failures.append(f"{case}: compression {ref['compression']} exceeds {g['max_compression']}")
        for mode in ("soft", "hard"):
            scores = [r["score"] for r in sorted(runs, key=lambda r: r["budget"]) if r["mode"] == mode]
            if scores != sorted(scores):
                failures.append(f"{case} {mode}: the score drops although the budget grows: {scores}")
    return failures


def baseline_key(result: dict[str, Any]) -> str:
    return f"{result['budget']}-{result['mode']}"


def compare_baseline(results: list[dict[str, Any]], baseline: dict[str, Any]) -> list[str]:
    measured_with = baseline.get("estimator", "markdown characters / 4")
    if baseline and measured_with != tokens.ESTIMATOR:
        # Budgets mean something else with another token estimate: compare only after a deliberate update.
        return [f"the baseline was measured with the token estimate '{measured_with}', the current one is "
                f"'{tokens.ESTIMATOR}': run --update-baseline and document the change in docs/quality.md"]  # fmt: skip
    failures = []
    for r in results:
        old = baseline.get(r["case"], {}).get(baseline_key(r))
        if old is None:
            continue
        run = f"{r['case']} {r['budget']} {r['mode']}"
        if r["score"] < old["score"] - REGRESSION_TOLERANCE:
            failures.append(f"{run}: CQS fell from {old['score']} to {r['score']} (tolerance {REGRESSION_TOLERANCE})")
        if r["critical_found"] < old["critical_found"]:
            failures.append(f"{run}: critical items fell from {old['critical_found']} to {r['critical_found']}")
    return failures


def baseline_from(results: list[dict[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {"estimator": tokens.ESTIMATOR}
    for r in results:
        data.setdefault(r["case"], {})[baseline_key(r)] = {
            "score": r["score"],
            "critical_found": r["critical_found"],
            "critical_total": r["critical_total"],
        }
    return data


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}


if __name__ == "__main__":
    sys.exit("use quality/run.py")
