# Pack format

## Files

`pack` writes into the project:

```
.context-bridge/
├── .gitignore        "*" - the store is never committed
├── packs/<id>.json   authoritative pack (the newest 10 are kept)
├── packs/<id>.md     portable Markdown rendering
├── latest.json
└── latest.md
```

Approvals live outside the project in `$XDG_STATE_HOME/context-bridge/consent/`, so a
repository cannot ship its own approval.

## Sections and tiers

| Tier | Sections | When the budget is tight |
|---|---|---|
| critical | goals, constraints, decisions, next steps | kept by default; only `--hard-budget` drops them, reported as critical loss |
| important | current state, open questions, open tasks, commands | dropped after context |
| context | overview, conventions, stack, structure | dropped first |

## Items

Every item has a status, a source and optionally a line range:

- `[fact]` stated in a source · `[assumption]` marked as an assumption · `[uncertain]` hedged,
  open or unlabeled
- `— S3 docs/roadmap.md:12` file source and lines · `(also in S5)` merged duplicate ·
  `(unverified)` from the session handoff
- flags: `redacted` (a secret or personal value was replaced), `instruction_like` (shown as data,
  never followed), `truncated` (shortened), `unlabeled` (handoff entry without status)

## Coverage

`coverage.status` is `all_extracted_items_kept`, `partial` or `critical_loss`, with the counts
it is derived from. `verify` recomputes it; a pack that overstates its coverage fails.

## Verification results

| Result | Meaning | What to do |
|---|---|---|
| `ok` | integrity, safety and freshness checks passed | use the pack, still check items before acting |
| `ok_with_warnings` | e.g. changed or missing sources, rewritten git history, partial coverage, old pack | name the warnings; re-check outdated items |
| `critical_information_loss` | the pack records dropped critical items | warn first; offer a new pack with a larger budget |
| `failed` | modified, forged, unsafe or broken pack | do not use it; offer a new pack |

Common findings: `source_changed` / `source_missing` (items listed as outdated),
`repository_progressed` (info: new commits or uncommitted work; source files are compared by
content, so this alone never makes an item outdated), `git_history_rewritten` (the pack's
commit is no longer in the history; the git snapshot is outdated),
`item_not_in_source` (an item cannot be derived from its unchanged file: forged),
`content_hash_mismatch` / `markdown_modified` (edited after writing), `coverage_misstated`,
`secret_in_pack`, `delimiter_in_pack`, `unflagged_instruction`, `trust_notice_altered`.
