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
| M7 Self-integration | `setup`: CLAUDE.md block with preview id, backup and undo; protected locations | Idempotent install and exact undo |
| M7.1 Auto-resume | Optional SessionStart hook that loads a verified digest; calibrated token estimate; git freshness that separates repository progress from source changes | Digest within its token limit in real sessions |
| M8 Release preparation | README and docs for users and contributors, community files, CI on Linux and macOS with Python 3.11–3.15, fresh-install smoke test | Fresh install works in an isolated home folder |
| M9 Windows and WSL 2 | Platform layer (home and data folders, unsafe Windows names, junctions, path keys, retries, UTF-8 output), Windows install with a directory junction, exec-form hook, PowerShell forms in the skill, CI on Windows | CI green on Linux, macOS and Windows; fresh install works on Windows |
| M10 Smart extraction | Text under unrecognised headings sorted by its wording or kept as unclassified notes, statement splitting, skipped boilerplate, extraction report, source coverage in the Context Quality Score | No silent loss of text under free headings; the unstructured `notes` case scores ≥ 90 |

Status: M0–M10 done: version 0.1.0, version 0.2.0 (Windows and WSL 2) and version 0.3.0 (smart
extraction). CI tests every change on Linux, macOS and Windows with Python 3.11–3.15. Claude Code
itself on Windows is not tested yet.

## Planned after the MVP

- **Self-integration** (`/context-bridge setup`): detect existing CLAUDE.md files (global and
  project, symlinks resolved), offer a global or project integration, show a preview and apply
  it only with a separate confirmation tied to that preview, avoid duplicate entries (marked
  block, idempotent) and allow undo from a backup. Done in M7.

## Later improvements to smart extraction

Left out of M10 on purpose, to keep it small:

- Checklist templates and milestone tables are read as open tasks, because their headings are
  recognised; a release checklist then looks like open release work.
- Cue phrases exist for English and German only, and a project cannot add its own phrases or
  skipped headings.
- Source coverage is measured for Markdown only; manifests and changelogs are read field by field.

## Compression priority

1. **Critical** – never dropped silently: goals, constraints, decisions, next steps
2. **Important** – current state, open questions, open tasks, commands
3. **Context** – overview, conventions, stack, structure

## Validation vs. quality

- **Structural validation** (`verify`): is the pack well-formed, consistent and traceable?
- **Semantic quality** (Context Quality Score): does the pack still contain what matters?
  Measured offline against synthetic reference cases with known ground truth.
