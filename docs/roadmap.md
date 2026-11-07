# Roadmap

The MVP ends with a skill that works locally. Publishing, a plugin wrapper, a marketplace
entry and further integrations come after the MVP.

| Milestone | Scope | Done when |
|---|---|---|
| M0 Skeleton | Repository layout, entry point, CLI skeleton, test helpers, CI, privacy guard | Tests green, `cb.py --version` works, guard blocks personal data |
| M1 Safety core | Path confinement, symlink/special-file checks, deny/allow policy, config layering, secret and PII redaction, prompt-injection detection, hardened git runner | Negative test for every rule |
| M2 `scan` | File discovery (git or walk), classification, exclusion reasons, findings, text and JSON output | Golden test, "writes nothing" test, works without git |
| M3 `pack` | Extractors, session handoff input, three-tier budget (critical, important, context), Markdown rendering, store, consent | Critical items are never dropped silently; critical loss is reported with exit code 3 |
| M4 `verify` + `resume` | Structural validation, integrity, freshness, safety re-scan, change summary, untrusted-data wrapper | Tampering and stale sources are detected |
| M5 Context Quality Score | Synthetic reference cases with ground truth; weighted retention of goals, constraints, decisions, next steps and facts | CQS ≥ 90 at the default budget, 100 % of critical items kept, no forbidden content |
| M6 Skill | `SKILL.md`, references, local end-to-end test in Claude Code | Save and resume work in a real session |

## Compression priority

1. **Critical** – never dropped silently: goals, constraints, decisions, next steps
2. **Important** – current state, open questions, open tasks, commands
3. **Context** – overview, conventions, stack, structure

## Validation vs. quality

- **Structural validation** (`verify`): is the pack well-formed, consistent and traceable?
- **Semantic quality** (Context Quality Score): does the pack still contain what matters?
  Measured offline against synthetic reference cases with known ground truth.
