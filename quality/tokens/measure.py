"""Measure the real token counts of the calibration samples with Claude Code.

Developer tool, not part of the skill: it needs the ``claude`` command line tool, sends the
samples to the model and costs a few cents per run. Tests and CI never run it.

Method: every sample is appended to the system prompt of a minimal headless session in an
empty directory (no tools, no MCP servers, no settings, hooks or plugins, no skills). The
prompt size of the first request is read from the reported usage. A sample's token count
is that size minus the size of the same session without a sample, minus the separator
overhead, which is measured with a one-character sample. The session without a sample runs
first and last; differing values mean the measurement was not stable.

    python3 -I quality/tokens/measure.py [--model haiku] [--only NAME ...] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCP_NONE = '{"mcpServers":{}}'


def prompt_tokens(cwd: Path, model: str, sample: Path | None = None) -> tuple[int, str, float]:
    """(prompt tokens of the first request, model id, reported cost in USD)."""
    cmd = ["claude", "-p", "Reply with OK.", "--model", model, "--tools", "", "--strict-mcp-config",
           "--mcp-config", MCP_NONE, "--setting-sources", "project", "--disable-slash-commands",
           "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk"]  # fmt: skip
    if sample is not None:
        cmd += ["--append-system-prompt", sample.read_text(encoding="utf-8")]
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=300, check=True).stdout
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    first = next(e for e in events if e.get("type") == "assistant")
    usage = first["message"]["usage"]
    tokens = (
        usage["input_tokens"] + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
    )
    cost = next((e.get("total_cost_usd") or 0.0 for e in events if e.get("type") == "result"), 0.0)
    return tokens, first["message"]["model"], cost


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="haiku", help="model alias or id passed to claude --model")
    parser.add_argument("--only", nargs="*", help="sample file names to measure (default: all)")
    parser.add_argument("--out", type=Path, default=HERE / "measurements.json")
    args = parser.parse_args()
    samples = sorted(p for p in (HERE / "samples").iterdir() if not args.only or p.name in args.only)
    cost = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        one = Path(tmp) / "one-character.txt"
        one.write_text("x", encoding="utf-8")
        base_first, model_id, c = prompt_tokens(work, args.model)
        cost += c
        with_one, _, c = prompt_tokens(work, args.model, one)
        cost += c
        separator = with_one - base_first - 1  # "x" is one token
        rows = []
        for sample in samples:
            total, _, c = prompt_tokens(work, args.model, sample)
            cost += c
            text = sample.read_text(encoding="utf-8")
            rows.append({"sample": sample.name, "characters": len(text), "tokens": total - base_first - separator})
            print(f"{sample.name:20} {len(text):6} characters {rows[-1]['tokens']:6} tokens", flush=True)
        base_last, _, c = prompt_tokens(work, args.model)
        cost += c
    result = {
        "model": model_id,
        "measured_on": datetime.now(UTC).strftime("%Y-%m-%d"),
        "method": "claude -p, sample appended to a minimal system prompt; prompt tokens minus the same "
        "session without the sample, minus the separator (see quality/tokens/measure.py)",
        "baseline_tokens": [base_first, base_last],
        "separator_tokens": separator,
        "samples": rows,
    }
    if args.out.exists() and args.only:  # merge a partial run into the existing file
        old = json.loads(args.out.read_text(encoding="utf-8"))
        merged = {r["sample"]: r for r in old.get("samples", [])} | {r["sample"]: r for r in rows}
        result["samples"] = [merged[k] for k in sorted(merged)]
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"model {model_id} · baseline {base_first}/{base_last} · separator {separator} · cost {cost:.4f} USD")
    return 0 if base_first == base_last else 1


if __name__ == "__main__":
    sys.exit(main())
