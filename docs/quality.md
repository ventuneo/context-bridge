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
- **Efficiency**: tokens of the rendered Markdown pack (everything a reader gets, including the
  trust notice, coverage line and sources table), tokens read from the sources, compression ratio
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

## Token estimate

Budgets, pack sizes and the efficiency metrics use `tokens.estimate`, which is calibrated against
real token counts. The standard library has no tokenizer, so the estimate is a weighted sum of six
counts. A line is German when it has more German than English function words; a line without any
follows the whole text.

| Feature | Tokens each |
|---|---|
| letter on an English line | 0.344 |
| letter on a German line | 0.510 |
| ASCII punctuation | 0.912 |
| digit | 1.293 |
| other symbol (`—`, `·`, `…`, `⚠`) | 0.785 |
| line break | 1.025 |

**Calibration** (`quality/tokens/`):

- 16 synthetic samples: English and German prose, the reference case files, five rendered packs,
  a resume output, a hook digest, Markdown with a table, code and JSON, and manifests.
- `measure.py` measured each sample with Claude Code. The sample is appended to the system prompt
  of a minimal headless session. Its token count is the prompt size minus the size of the same
  session without it.
- `calibrate.py` fits the weights by weighted least squares on the relative error.
- Claude Haiku 5.5 and Opus 5.5 counted exactly the same tokens on the four samples measured with
  both models.

| Estimate | Mean error | Largest error |
|---|---|---|
| `characters / 4` (before) | 39 % | 49 % (German) |
| calibrated, leave-one-out | 4.3 % | 10.2 % |

`characters / 4` undercounted every sample: English prose by about 20 %, German text, packs and
Markdown by 40 to 50 %. `tokens.upper_bound` adds the largest calibration error (11 %). The
SessionStart hook uses it, so its digest stays within `[hook] max_tokens`.

`tests/test_tokens.py` keeps the estimate tied to the data:

- every sample is estimated within the stated error;
- a fresh fit gives the weights in use;
- the upper bound is never below a real count.

To recalibrate, run these steps in order:

1. `make_samples.py`
2. `measure.py` (sends the samples to the model; costs a few cents)
3. `calibrate.py`
4. Copy the weights into `tokens.py` and give `ESTIMATOR` a new name.
5. Update the baseline.

### Effect on the scores (8 November 2026)

The same packs are now counted honestly, so a budget holds less content than before. In the
`large` case, a pack that `characters / 4` called 2000 tokens was about 3900 real tokens.

CQS before → after, per budget:

| Case | Mode | 500 | 1000 | 2000 | 4000 |
|---|---|---|---|---|---|
| `basic` | soft | 71.2 → 71.2 | 98.3 → 71.2 | 100 → 100 | 100 → 100 |
| `basic` | hard | 10.2 → 0 | 98.3 → 20.3 | 100 → 100 | 100 → 100 |
| `conflicts` | soft | 73.5 → 58.8 | 100 → 85.3 | 100 → 100 | 100 → 100 |
| `conflicts` | hard | 73.5 → 0 | 100 → 85.3 | 100 → 100 | 100 → 100 |
| `german` | soft | 75 → 75 | 100 → 75 | 100 → 100 | 100 → 100 |
| `german` | hard | 20 → 0 | 100 → 25 | 100 → 100 | 100 → 100 |
| `injection` | soft | 91.2 → 91.2 | 100 → 91.2 | 100 → 100 | 100 → 100 |
| `injection` | hard | 26.5 → 0 | 100 → 47.1 | 100 → 100 | 100 → 100 |
| `large` | soft | 81.3 → 81.3 | 81.3 → 81.3 | 97.1 → 81.3 | 100 → 97.1 |
| `large` | hard | 4.3 → 0 | 41 → 12.9 | 97.1 → 49.6 | 100 → 97.1 |

What did not change:

- In `soft` mode every critical item survives at every budget.
- Every critical loss in `hard` mode is reported.
- Status and provenance accuracy stay at 100 %.
- All gates pass.

`large` keeps every goal, constraint, decision and next step at its reference budget of 4000,
but it leaves out 4 of its 8 normal facts and reports the coverage as `partial`. It reaches 99.3
at 5000 tokens and 100 at about 5850. The pack loop now also uses room that is left after
rendering, which is why `basic` keeps every item at 2000.

The baseline records the estimate it was measured with (`"estimator": "calibrated-v1"`). `--check`
fails when that differs from the estimate in use, so a recalibration always comes with a
deliberate new baseline.

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
- Token counts are estimates: about 4 % off on average and up to about 10 % on the calibration
  samples (see «Token estimate»). Tokenizers other than Claude's may count differently.
- Under `--hard-budget` the critical tier is cut in section order (goals, constraints,
  decisions, next steps), so later critical sections are lost first.
