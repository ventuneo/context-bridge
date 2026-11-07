# Context Bridge

Context Bridge is a skill for Claude Code that extracts project context from approved
sources, compresses it into a small, source-anchored **context pack**, verifies it and
restores it in a new AI session. Packs are plain JSON and Markdown, so they also work
with other assistants.

> **Status:** early development. `scan` works; `pack`, `resume` and `verify` are planned.
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
| `pack`   | Build a compressed context pack                                | planned |
| `resume` | Restore context in a new session                               | planned |
| `verify` | Check structure, integrity, freshness and safety of a pack     | planned |

```sh
python3 -I skills/context-bridge/scripts/cb.py scan --root path/to/project
python3 -I skills/context-bridge/scripts/cb.py scan --root path/to/project --json
```

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
