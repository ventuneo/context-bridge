# Context Bridge

Context Bridge is a skill for Claude Code that extracts project context from approved
sources, compresses it into a small, source-anchored **context pack**, verifies it and
restores it in a new AI session. Packs are plain JSON and Markdown, so they also work
with other assistants.

> **Status:** early development. `scan`, `pack`, `verify`, `resume` and the Claude Code skill
> (`skills/context-bridge/SKILL.md`) work locally. Not published yet.

## Principles

- **Local only.** No network access; packs live in the project under `.context-bridge/`.
- **Standard library only.** Python 3.11+, no runtime dependencies.
- **Allowlist first.** Only documentation and manifests are read; source code is counted, not read.
- **Traceable.** Every item in a pack points to its source file, line range and SHA-256.
- **Untrusted by default.** Pack content is data, never instructions; secrets are redacted,
  prompt-injection patterns and invisible Unicode are flagged.

## Commands

| Command  | Purpose                                                        | Status  |
|----------|----------------------------------------------------------------|---------|
| `scan`   | Show which files may be used and why others are excluded       | done    |
| `pack`   | Build a compressed context pack from approved sources          | done    |
| `resume` | Verify the latest pack and print it for a new session          | done    |
| `verify` | Check structure, integrity, safety and freshness of a pack     | done    |
| `setup`  | Integrate into CLAUDE.md or a SessionStart hook, with preview  | done    |

```sh
CB="python3 -I skills/context-bridge/scripts/cb.py"
$CB scan --root path/to/project                   # what may be used, and why not the rest
$CB pack --root path/to/project --approve         # first pack: approve the current sources
echo '{"next_steps": [{"text": "Write verify", "status": "fact"}]}' \
  | $CB pack --root path/to/project --handoff -   # add a session handoff from stdin
$CB pack --root path/to/project --dry-run         # print the pack, write nothing
$CB verify --root path/to/project                 # integrity, safety, freshness of the latest pack
$CB resume --root path/to/project                 # verified pack, wrapped as untrusted data
```

### Integration (setup)

`/context-bridge setup` (or `cb.py setup`) adds a short, marked Context Bridge block to a CLAUDE.md
file and, optionally, a SessionStart hook that prints a one-line notice when a project has a pack.

```sh
$CB setup status --root .                                   # which CLAUDE.md files exist, what is protected
$CB setup preview --target global|project|local --root .    # diff and preview id, writes nothing
$CB setup apply --target project --confirm <id> --root .    # writes exactly the previewed change
$CB setup undo-preview --target project --root .            # diff of the undo
$CB setup undo --target project --confirm <id> --root .     # restore the backup
$CB setup preview --target global --hook --root .           # the optional hook, same steps
```

- Nothing is written without a preview id; a file that changed after the preview is refused.
- Every write is backed up in `$XDG_STATE_HOME/context-bridge/setup/`; undo restores it exactly, or
  removes only Context Bridge's own block or hook entry when the file changed since.
- Idempotent: a second run changes nothing; other mentions of Context Bridge and a block in another
  scope are reported instead of written twice.
- Never written: symlinked targets, files inside an Obsidian vault, denied locations and
  `[setup] protected_roots` from the user config, invalid settings files.
- The skill may run `status`, `preview` and `undo-preview` on its own; `apply` and `undo` always ask.

### Quality

The Context Quality Score measures, on five synthetic reference projects including a large one,
how many goals, constraints, decisions, next steps and facts survive compression at budgets
from 500 to 4000 tokens, whether statuses and sources are right, and how much smaller the
pack is than its sources. See [docs/quality.md](docs/quality.md).

```sh
python3 -I quality/run.py --check
```

### Verification

- **Structure:** `schema.validate` (standard library) and the published JSON Schema in
  `schema/context-pack-v1.schema.json` for other tools.
- **Integrity:** fingerprint, content hash, pack id and Markdown hash are recomputed.
- **Provenance:** for every unchanged source file, each item must be re-derivable by the same
  extractor. A forged item is detected even if all hashes were recomputed.
- **Safety:** secrets, personal data, hidden characters, wrapper delimiters, unflagged
  instruction-like text, an altered trust notice and unsafe source paths are errors.
- **Freshness:** changed and missing sources, outdated items, new commits, rewritten history,
  new sources and the pack age (default limit 14 days).
- `resume` never shows a pack that fails verification. Everything that comes from the project is
  inside `<context_bridge_pack trust="untrusted-data">`, escaped so it cannot close the wrapper.

### Packs

- `pack` writes `<project>/.context-bridge/packs/<id>.json` (authoritative) and `.md`
  (portable: paste it into any assistant), plus `latest.json` and `latest.md`.
  The store ignores itself in git; directories are 0700, files 0600, writes are atomic.
- **Priorities:** critical (goals, constraints, decisions, next steps) > important
  (state, open questions, open tasks, commands) > context (overview, conventions, stack,
  structure). Context is dropped first. Critical items are kept even if that exceeds the
  budget; with `--hard-budget` they may be dropped, and that is reported as
  **critical information loss** (banner in the pack, message on stderr, exit code 3).
- **Coverage:** every pack states whether all extracted items are kept, the pack is `PARTIAL`, or
  it records `CRITICAL INFORMATION LOSS`; `verify` recomputes it. A pack is never called complete:
  extraction is selective. The budget covers the whole rendered Markdown.
- Every item carries its source (file, line range, SHA-256) and a status:
  `fact`, `assumption` or `uncertain`. Duplicates are merged and their sources kept.
- **Consent:** new sources are never packed until approved (`--approve` or
  `--approve-path`). Approvals are stored outside the project in
  `$XDG_STATE_HOME/context-bridge/consent/` (default `~/.local/state`), so a repository
  cannot ship its own approval.

Exit codes: `0` ok · `1` warnings · `2` error or blocked · `3` critical information loss · `64` usage error.

## Development

```sh
python3 -m unittest discover -s tests          # run all tests
git config core.hooksPath .githooks            # enable the privacy guard hooks
python3 tools/privacy_check.py --history       # scan the whole history for personal data
```

The privacy guard blocks absolute home paths, personal e-mail addresses and any term
listed in the local, unversioned file `.git/info/private-terms`.

See [docs/roadmap.md](docs/roadmap.md) for the milestone plan.

## License

MIT, see [LICENSE](LICENSE).
