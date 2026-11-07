#!/usr/bin/env python3
"""Run the Context Quality Score over all reference cases.

    python3 -I quality/run.py                      # table for every case, budget and mode
    python3 -I quality/run.py --case large --details --budget 2000
    python3 -I quality/run.py --check              # gates + baseline, exit 1 on failure (CI)
    python3 -I quality/run.py --update-baseline    # store the current results as the baseline
    python3 -I quality/run.py --json

Modes: "soft" is the default packing (critical items are protected, the budget may be
exceeded); "hard" is --hard-budget (the budget is never exceeded and critical loss
is reported).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate  # noqa: E402


def _ratio(pair: list[int] | None) -> str:
    return f"{pair[0]}/{pair[1]}" if pair else "-"


def table(results: list[dict]) -> str:
    head = (
        f"{'case':<10} {'budget':>6} {'mode':<4} {'CQS':>5} {'points':>7} {'crit':>6} {'goal':>5} {'constr':>6} "
        f"{'decis':>5} {'next':>5} {'status':>6} {'origin':>6} {'tokens':>6} {'read':>6} {'ratio':>6} "
        f"{'pts/1k':>6} {'exit':>4}  critical loss"
    )
    lines = [head, "-" * len(head)]
    for r in results:
        cat = r["by_category"]
        pct = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
        loss = ", ".join(r["critical_missing"])
        loss = f"CRITICAL LOSS {loss}" + (" (reported)" if r["loss_reported"] else " (NOT REPORTED)") if loss else "-"
        lines.append(
            f"{r['case']:<10} {r['budget']:>6} {r['mode']:<4} {r['score']:>5} {r['points']:>3}/{r['max_points']:<3} "
            f"{r['critical_found']:>2}/{r['critical_total']:<3} {_ratio(cat.get('goal')):>5} "
            f"{_ratio(cat.get('constraint')):>6} "
            f"{_ratio(cat.get('decision')):>5} {_ratio(cat.get('next_step')):>5} {pct(r['status_accuracy']):>6} "
            f"{pct(r['provenance_accuracy']):>6} {r['tokens']:>6} {r['source_tokens']:>6} {r['compression']:>6} "
            f"{r['points_per_1k_tokens']:>6} {r['pack_exit']}/{r['verify_exit']}  {loss}"
        )
    return "\n".join(lines)


def details(result: dict) -> str:
    lines = [
        f"{result['case']} budget {result['budget']} {result['mode']}: CQS {result['score']} = "
        f"{result['points']} of {result['max_points']} points",
        "",
    ]
    lines.append(f"{'id':<5} {'criticality':<10} {'category':<14} {'found':<6} {'item':<5} status origin flags")
    for v in result["items"]:
        marks = " ".join(
            "ok" if v.get(f"{k}_ok") else ("WRONG" if f"{k}_ok" in v else "-")
            for k in ("status", "provenance", "flags")
        )
        lines.append(
            f"{v['id']:<5} {v['criticality']:<10} {v['category']:<14} {'yes' if v['found'] else 'NO':<6} "
            f"{v['item'] or '-':<5} {marks}"
        )
    for kind, entries in result["mismatches"].items():
        lines += ["", f"{kind} mismatches:"] + [
            f"  {e['id']}: expected {e['expected']}, got {e['actual']}" for e in entries
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Context Quality Score over the synthetic reference cases")
    parser.add_argument("--case", action="append", help="limit to a case (repeatable)")
    parser.add_argument("--budget", action="append", type=int, help="limit to a budget (repeatable)")
    parser.add_argument("--details", action="store_true", help="per-item verdicts")
    parser.add_argument("--json", action="store_true", help="machine-readable results")
    parser.add_argument("--check", action="store_true", help="apply the gates and the baseline; exit 1 on failure")
    parser.add_argument("--update-baseline", action="store_true", help="store the results as the new baseline")
    args = parser.parse_args(argv)
    cases = [evaluate.CASES / c for c in args.case] if args.case else None
    budgets = tuple(args.budget) if args.budget else evaluate.BUDGETS
    results = evaluate.run_matrix(cases, budgets)
    if args.json:
        json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(table(results))
        if args.details:
            for r in results:
                print("\n" + details(r))
    if args.update_baseline:
        if cases or args.budget:
            print("--update-baseline needs the full matrix (no --case or --budget)", file=sys.stderr)
            return 2
        evaluate.BASELINE.write_text(json.dumps(evaluate.baseline_from(results), indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {evaluate.BASELINE.name}")
    if args.check:
        failures = evaluate.check_gates(results) + evaluate.compare_baseline(results, evaluate.load_baseline())
        print("\nGates: " + ("PASS" if not failures else f"FAIL ({len(failures)})"))
        for failure in failures:
            print(f"  - {failure}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
