# Context Bridge

Context Bridge is a skill for Claude Code that extracts project context from approved
sources, compresses it into a small, source-anchored **context pack**, verifies it and
restores it in a new AI session. Packs are plain JSON and Markdown, so they also work
with other assistants.

> **Status:** early development. `scan` and `pack` work; `resume` and `verify` are planned.
> Not ready for everyday use yet.

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
| `resume` | Restore context in a new session                               | planned |
| `verify` | Check structure, integrity, freshness and safety of a pack     | planned |

```sh
CB="python3 -I skills/context-bridge/scripts/cb.py"
$CB scan --root path/to/project                   # what may be used, and why not the rest
$CB pack --root path/to/project --approve         # first pack: approve the current sources
echo '{"next_steps": [{"text": "Write verify", "status": "fact"}]}' \
  | $CB pack --root path/to/project --handoff -   # add a session handoff from stdin
$CB pack --root path/to/project --dry-run         # print the pack, write nothing
```

### Packs

- `pack` writes `<project>/.context-bridge/packs/<id>.json` (authoritative) and `.md`
  (portable: paste it into any assistant), plus `latest.json` and `latest.md`.
  The store ignores itself in git; directories are 0700, files 0600, writes are atomic.
- **Priorities:** critical (goals, constraints, decisions, next steps) > important
  (state, open questions, open tasks, commands) > context (overview, conventions, stack,
  structure). Context is dropped first. Critical items are kept even if that exceeds the
  budget; with `--hard-budget` they may be dropped, and that is reported as
  **critical information loss** (banner in the pack, message on stderr, exit code 3).
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
