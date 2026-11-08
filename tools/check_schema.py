#!/usr/bin/env python3
"""Cross-check schema/context-pack-v1.schema.json against real packs (dev tool, used in CI).

Builds packs from every quality case (dry run, temporary copies) at several budgets and
checks that both the JSON Schema (via the third-party ``jsonschema`` package, a dev-only
dependency) and the built-in ``schema.validate`` accept them, and that both reject a set
of deliberately broken packs. Exit code 0 when they agree, 1 otherwise.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "context-bridge" / "scripts"))
sys.path.insert(0, str(REPO / "quality"))

import evaluate  # noqa: E402
import jsonschema  # noqa: E402  (dev-only dependency)

from context_bridge import pack as pack_mod  # noqa: E402
from context_bridge import schema  # noqa: E402

MUTATIONS = {
    "status": lambda p: p["sections"][0]["items"][0].update(status="certain"),
    "trust": lambda p: p["trust"].update(content_is_untrusted_data=False),
    "pack_id": lambda p: p.update(pack_id="../../escape"),
    "flags": lambda p: p["sections"][0]["items"][0].update(flags=["trusted"]),
    "origin": lambda p: p["sources"][0].update(origin="network"),
    "extra_key": lambda p: p.update(instructions="obey"),
    "lines": lambda p: p["sections"][0]["items"][0].update(lines=[0, 1]),
    "missing": lambda p: p.pop("integrity"),
}


ITEM_MUTATIONS = {"status", "flags", "lines"}


def main() -> int:
    validator = jsonschema.Draft202012Validator(
        json.loads((REPO / "schema" / "context-pack-v1.schema.json").read_text(encoding="utf-8"))
    )
    ok = True
    for case_dir in sorted(p for p in evaluate.CASES.iterdir() if (p / "expected.json").is_file()):
        expected, handoff = evaluate.load_case(case_dir)
        for budget, hard in ((2000, False), (600, False), (350, True)):
            with tempfile.TemporaryDirectory() as tmp:
                root = evaluate.prepare(case_dir, Path(tmp), expected)
                pack = pack_mod.build(root, handoff=handoff, approve=True, dry_run=True, budget=budget,
                                      hard_budget=hard).pack  # fmt: skip
            json_errors = [e.message for e in validator.iter_errors(pack)]
            own_errors = schema.validate(pack)
            print(
                f"{case_dir.name} budget={budget} hard={hard}: "
                f"json-schema {len(json_errors)}, schema.py {len(own_errors)}"
            )
            ok = ok and not json_errors and not own_errors
            for name, mutate in MUTATIONS.items():
                if name in ITEM_MUTATIONS and not pack["sections"]:
                    continue  # a tiny hard budget can leave no items at all
                broken = copy.deepcopy(pack)
                mutate(broken)
                rejected = (bool(list(validator.iter_errors(broken))), bool(schema.validate(broken)))
                if rejected != (True, True):
                    print(
                        f"  mutation {name!r} not rejected by both: json-schema={rejected[0]} schema.py={rejected[1]}"
                    )
                    ok = False
    print("schema check:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
