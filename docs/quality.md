# Context Quality Score (CQS)

Context Bridge answers two different questions about a pack:

| | Structural validation | Semantic quality (CQS) |
|---|---|---|
| Question | Is the pack well-formed, unmodified, safe and fresh? | Does the pack still contain what matters? |
| Tool | `verify` (runs on every pack) | `quality/run.py` over synthetic reference cases |
| Basis | schema, hashes, provenance, current files | ground truth written for each case |

## Reference cases

All cases are synthetic. Placeholders such as `{{FAKE_GITHUB_TOKEN}}` are replaced at runtime,
so the repository never contains secret-looking strings.

| Case | Size | What it stresses |
|---|---|---|
| `basic` | small | English with a German note, ADRs, roadmap, session handoff, a secret, an e-mail, hidden comment text |
| `german` | small | German only: German headings, `Ziel:`/`Status:`/`Nächster Schritt:` lines, assumptions, open points |
| `conflicts` | small | contradicting goal and decision, superseded ADR, the same statement in the session and a file |
| `injection` | small | instruction-like text, fake system tags, hidden comments, invisible tag characters, secrets, personal data |
| `large` | large | 10 ADRs, two rule files, roadmap, operations, 40 generated guides, 400 code files, about 23 000 tokens read |

Each case has `project/`, `handoff.json` and `expected.json`. Every expected item has an id,
a category (goal, constraint, decision, next_step, fact, assumption, open_question), a
criticality (critical, important, normal), matching terms (`all` must occur in one pack
item after Unicode and case normalisation) and optionally the expected status, origin
(`file` or `session`), source file and flags. `forbidden` lists content that must never
appear anywhere in the pack.

## Metrics

Every number is counted from the ground truth:

- **CQS** = 100 × points found / points possible, with critical = 3, important = 2,
  normal = 1 point. The output always shows both numbers, for example `135/139`.
- **Critical recall** and the ids of missing critical items.
- **Recall per category** (goals, constraints, decisions, next steps, ...).
- **Status accuracy**: fact, assumption and uncertain as expected.
- **Provenance accuracy**: file-backed statements are attributed to their file; session
  notes are attributed to the session handoff and marked `(unverified)` in Markdown.
- **Flag accuracy**: `redacted`, `instruction_like`, `unlabeled`.
- **Forbidden hits** in the JSON and the Markdown.
- **Efficiency**: pack tokens, tokens read from the sources, compression ratio
  (pack ÷ sources) and points per 1000 pack tokens.
- **Loss reporting**: whether `pack` (exit 3) and `verify` (exit 3) report a critical loss.

Each case runs at budgets 500, 1000, 2000 and 4000 in two modes: `soft` (default: critical
items are protected, the budget may be exceeded) and `hard` (`--hard-budget`: the budget is
never exceeded).

## Gates

`python3 -I quality/run.py --check` fails when any of these is violated:

1. No forbidden content in any run.
2. `verify` reports no errors on any genuine pack.
3. No critical item is missing in `soft` mode.
4. Every critical loss in `hard` mode is reported by `pack` and `verify` (exit 3).
5. At the case's reference budget (2000; `large`: 4000): CQS ≥ 90 and status, provenance
   and flag accuracy of 100 %.
6. `large`: compression ratio ≤ 0.2 at the reference budget.
7. The score never drops when the budget grows.
8. No regression against `quality/baseline.json` (CQS may not fall by more than 5 points,
   critical recall may not fall at all).

## Running

```sh
python3 -I quality/run.py                                 # table for all cases and budgets
python3 -I quality/run.py --case large --budget 1000 --details   # verdict per expected item
python3 -I quality/run.py --check                         # gates and baseline (used in CI)
python3 -I quality/run.py --update-baseline               # after an intended change, reviewed
```

## Limits

- Matching is lexical. This suits an extractive packer, but paraphrases in a session
  handoff would not be recognised.
- The cases are written by the developers of the packer; they show the intended behaviour
  and catch regressions, but they are not an independent benchmark.
- Token counts are estimates (characters ÷ 4).
- Under `--hard-budget` the critical tier is cut in section order (goals, constraints,
  decisions, next steps), so later critical sections are lost first.
