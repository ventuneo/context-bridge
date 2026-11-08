"""Fit the token estimate to the measured samples and check the weights in use.

    python3 -I quality/tokens/calibrate.py          # fitted weights and errors per sample
    python3 -I quality/tokens/calibrate.py --check  # exit 1 if tokens.WEIGHTS no longer fit the data

The fit minimises the squared relative error over all samples (weighted least squares);
a feature that would get a negative weight is dropped and the fit repeated. The
leave-one-out error fits on all samples but one and estimates that one, so it shows how
the estimate does on text it was not fitted to.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "context-bridge" / "scripts"))

from context_bridge import tokens  # noqa: E402

TOLERANCE = 0.01  # relative difference between fitted and used weights that --check accepts


def load(path: Path = HERE / "measurements.json") -> list[tuple[str, str, int]]:
    """(sample name, text, measured tokens) for every measured sample."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        (row["sample"], (HERE / "samples" / row["sample"]).read_text(encoding="utf-8"), row["tokens"])
        for row in data["samples"]
    ]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(matrix)
    rows = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ValueError("the samples do not determine every weight")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                for c in range(col, n + 1):
                    rows[r][c] -= factor * rows[col][c]
    return [rows[i][n] / rows[i][i] for i in range(n)]


def fit(samples: list[tuple[str, str, int]], names: tuple[str, ...] = tuple(tokens.WEIGHTS)) -> dict[str, float]:
    feats = [(tokens.features(text), measured) for _name, text, measured in samples]
    active = list(names)
    while True:
        design = [[f[k] / measured for k in active] for f, measured in feats]  # relative error per sample
        normal = [[sum(r[i] * r[j] for r in design) for j in range(len(active))] for i in range(len(active))]
        weights = _solve(normal, [sum(r[i] for r in design) for i in range(len(active))])
        if min(weights) >= 0:
            return {k: (dict(zip(active, weights, strict=True)).get(k, 0.0)) for k in names}
        active.pop(weights.index(min(weights)))


def predict(weights: dict[str, float], text: str) -> float:
    counts = tokens.features(text)
    return sum(w * counts[k] for k, w in weights.items())


def leave_one_out(samples: list[tuple[str, str, int]]) -> dict[str, float]:
    errors = {}
    for index, (name, text, measured) in enumerate(samples):
        weights = fit(samples[:index] + samples[index + 1 :])
        errors[name] = (predict(weights, text) - measured) / measured
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="fit and check the calibrated token estimate")
    parser.add_argument("--check", action="store_true", help="exit 1 if tokens.WEIGHTS do not match the fit")
    args = parser.parse_args()
    samples = load()
    fitted = fit(samples)
    loo = leave_one_out(samples)
    print(f"{'sample':20} {'chars':>6} {'tokens':>6} {'chars/4':>8} {'estimate':>9} {'leave-one-out':>14}")
    for name, text, measured in samples:
        old = (len(text) / 4 - measured) / measured
        new = (tokens.estimate(text) - measured) / measured
        print(f"{name:20} {len(text):6} {measured:6} {old:+8.1%} {new:+9.1%} {loo[name]:+14.1%}")
    mean = sum(abs(e) for e in loo.values()) / len(loo)
    worst = max(abs(e) for e in loo.values())
    print(f"leave-one-out error: mean {mean:.1%}, largest {worst:.1%} (MAX_ERROR {tokens.MAX_ERROR:.0%})")
    print("fitted weights:", ", ".join(f"{k} {v:.4f}" for k, v in fitted.items()))
    drift = {k: abs(fitted[k] - w) / w for k, w in tokens.WEIGHTS.items()}
    if args.check and (max(drift.values()) > TOLERANCE or worst > tokens.MAX_ERROR):
        print("tokens.WEIGHTS or tokens.MAX_ERROR no longer match the measurements", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
