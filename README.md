# Context Bridge

**Verified, source-anchored context packs for Claude Code.** Save where a project stands, check
later that it is still true, and pick up the work in a new session.

[![CI](https://github.com/ventuneo/context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ventuneo/context-bridge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Platforms: macOS, Linux, Windows](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)

Context Bridge is a skill for Claude Code. It reads goals, constraints, decisions, next steps and
the current state from files you approve. It adds a short handoff from the conversation and writes
a **context pack**: JSON plus Markdown, in which every item names its source file, line range and
checksum. In the next session, `resume` checks the pack against the current files before it shows
anything.

> Context Bridge is an independent open-source project. It is not affiliated with or endorsed by
> Anthropic. Several unrelated projects on GitHub are also called "context-bridge"; this one is
> `ventuneo/context-bridge`.

## Why

- **Conversations end, projects continue.** A pack keeps what matters across sessions, machines and
  assistants: what was decided, what comes next and what is still open.
- **Every line can be checked.** Items come from a named file and line range. Items that come from
  the conversation are marked `(unverified)`.
- **It notices when it is out of date.** Changed files, outdated items and new commits are reported,
  and a tampered pack is refused.
- **It says what it left out.** Every pack states its coverage and is never called complete.

It complements `CLAUDE.md`, which holds rules that rarely change, and `claude --resume`, which
continues one conversation in one tool. A pack is a small, reviewable snapshot of the parts of a
project that move.

## Features

- **`scan`** shows which files may be used and why others are excluded. Only documentation and
  manifests are read. Source code is counted, never read, and secrets and keys are never opened.
- **`pack`** extracts items, merges duplicates and fits them into a token budget in this order:
  critical items (goals, constraints, decisions, next steps), then important ones (state, open
  questions, tasks, commands), then context. Dropping a critical item is reported as **critical
  information loss**.
- **`verify`** checks the structure, the integrity (hashes, re-rendering), the provenance (every item
  from an unchanged file must be re-derivable), the safety (secrets, hidden characters, injection)
  and the freshness (changed files, new commits, age).
- **`resume`** prints a verified pack for a new session. The pack is wrapped as untrusted data and
  followed by what changed since it was written.
- **`setup`** integrates Context Bridge into Claude Code: a two-line block in a CLAUDE.md file and
  an optional SessionStart hook that loads a short, verified digest when a session starts. Every
  change is previewed, confirmed, backed up and can be undone.
- **Private by design.** It runs locally with the Python standard library and has no network
  access. New sources need your approval, secrets and personal data are redacted, and folders you
  deny are never read.

## Requirements

- Python 3.11 or newer: `python3` on macOS, Linux and WSL; `python` or `py -3` on Windows
- Claude Code, to use the skill (the command line also works on its own); on Windows, 2.1.139 or
  newer for the optional SessionStart hook
- macOS, Linux, Windows 10 or 11, or WSL 2 (see [docs/platforms.md](docs/platforms.md))
- git, optional: with it, packs include the branch, recent commits and uncommitted changes

## Installation

Context Bridge is installed from this repository. It is not distributed through a plugin
marketplace.

```sh
git clone --branch v0.2.0 --depth 1 https://github.com/ventuneo/context-bridge.git ~/.local/share/context-bridge
mkdir -p ~/.claude/skills
ln -s ~/.local/share/context-bridge/skills/context-bridge ~/.claude/skills/context-bridge
python3 -I ~/.claude/skills/context-bridge/scripts/cb.py --version   # context-bridge 0.2.0
```

On Windows, in PowerShell (a directory junction instead of a symbolic link, so no administrator
rights are needed):

```powershell
git clone --branch v0.2.0 --depth 1 https://github.com/ventuneo/context-bridge.git "$env:LOCALAPPDATA\Programs\context-bridge"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\context-bridge" -Target "$env:LOCALAPPDATA\Programs\context-bridge\skills\context-bridge"
python -I "$env:USERPROFILE\.claude\skills\context-bridge\scripts\cb.py" --version   # or: py -3 -I ...
```

Then start a new Claude Code session. [docs/install.md](docs/install.md) covers WSL 2, installing
for a single project, verifying what you installed, updating and uninstalling.

## Using it in Claude Code

| You say | Context Bridge |
|---|---|
| "Save the context" | runs `scan`, asks you to approve the sources (the first time), writes the handoff, runs `pack` and `verify`, and reports the coverage |
| "Where were we?" | summarises the state and what changed, from `resume` or from the digest the optional hook loaded, and suggests the next step |
| "Is the saved context still accurate?" | runs `verify` |
| `/context-bridge setup` | lists your CLAUDE.md files and offers the integration, with a preview |

The skill recognises German requests too ("Kontext sichern", "wo waren wir"). It only runs
`python3 -I …/cb.py` commands (on Windows `python -I` or `py -3 -I`), and `setup apply` and
`setup undo` always ask for your confirmation.

## Demo

A run on the synthetic project in [`examples/demo-project`](examples/demo-project). The output is
real but shortened:

```text
$ cb scan --root .
Context Bridge scan: shelf (git)
Nothing was written.

Included: 4 files, 1.0 KB, ~352 tokens
  README.md                       readme           0.6 KB  ~209 tok
  CLAUDE.md                       agent_rules      0.1 KB  ~37 tok
  docs/decisions/0001-storage.md  decisions        0.2 KB  ~65 tok
  pyproject.toml                  manifest         0.1 KB  ~41 tok

Excluded: 1 entries
  not_in_allowlist           1   src/shelf/cli.py

Findings: 0 secrets, 0 personal data, 0 injection patterns. Values are never shown; pack will redact them.

$ cb pack --root . --approve --handoff-json '{"goal": {"text": "Ship reminders before the summer holidays.", "status": "fact"}, ...}'
Context pack written: .context-bridge/packs/20261108T013155Z-d22e74.md (JSON: .context-bridge/packs/20261108T013155Z-d22e74.json)
Latest: .context-bridge/latest.md
~1239 of 2000 tokens · kept 20 items (critical 11, important 4, context 5) · left out 0 · duplicates merged 0

$ cb verify --root .
Result: OK (integrity, safety and freshness checks passed)
Coverage: All 20 extracted items are included. Extraction is selective: text outside recognised sections is not in the pack, so the pack is not a full copy of the project.
Source files: 4 fresh
Repository: unchanged since the pack
```

An excerpt of the Markdown pack, `.context-bridge/latest.md`:

```markdown
## Goals
- [fact] Ship reminders before the summer holidays. — S7 session handoff (unverified)
- [fact] Lending a book takes one command and less than ten seconds. — S1 README.md:8

## Decisions
- [fact] Decision: Loans are stored in one TOML file, because people can read and fix it by hand. — S3 docs/decisions/0001-storage.md:3

## Next steps
- [fact] Write the reminder command and its tests. — S7 session handoff (unverified)
- [fact] Import an existing spreadsheet of books. — S1 README.md:19
```

After one line of the README changed and a commit was made, `resume` reports both separately:

```text
Since this pack: 1 new commit(s) · 1 changed and 0 missing source file(s) · 1 outdated item(s) · 0 new source(s)
...
## Changes since this pack

- Repository: 1 new commit(s) since the pack:
  - 4b6fcc8: Plan the CSV import
- Changed: S1 README.md; outdated items: I11
```

## Commands

| Command | Purpose | Writes |
|---|---|---|
| `scan` | show which files may be used, and why others are excluded | nothing |
| `pack` | build a pack from approved sources and an optional handoff | `.context-bridge/` in the project |
| `verify` | check structure, integrity, provenance, safety and freshness | nothing |
| `resume` | verify the latest pack and print it for a new session | nothing |
| `setup` | integrate into CLAUDE.md or a SessionStart hook | only after a preview and your confirmation |

```sh
cb() { python3 -I ~/.claude/skills/context-bridge/scripts/cb.py "$@"; }
cb scan --root .
cb pack --root . --approve            # first pack in a project: approve the listed sources
cb pack --root . --handoff-json '{"next_steps": [{"text": "Write the importer.", "status": "fact"}]}'
cb pack --root . --budget 4000        # more room for large projects (the default is 2000)
cb verify --root . --json
cb resume --root .
cb setup status --root .
```

Exit codes: `0` ok · `1` warnings · `2` failed or blocked · `3` critical information loss ·
`64` usage error.

## Integration with Claude Code

`/context-bridge setup` (or `cb setup`) offers two optional parts:

- A short, marked **block in a CLAUDE.md file** (global, project or local) that tells future
  sessions when to resume and when to offer a pack.
- The **auto-resume SessionStart hook**. When a session starts or resumes, it verifies the latest
  pack and loads a digest of about 350 tokens. In a project without a pack it loads nothing, and
  from a pack that fails verification it loads only a one-line warning. It never writes anything.

Nothing is written without a preview id. Every write is backed up, and `setup undo` restores the
backup exactly. See [docs/setup.md](docs/setup.md).

## How it works

```text
 approved files: README · CLAUDE.md · AGENTS.md · docs · ADRs · manifests · git metadata
 session handoff: JSON written by the assistant
        │
 scan   │ allowlist and deny roots · confined reads · redaction · injection checks
        ▼
 pack   │ extractors → items (source, lines, status) → duplicates merged → token budget
        ▼                                     → .context-bridge/latest.json + latest.md
 verify │ schema · hashes · re-rendering · provenance · safety re-scan · freshness
        ▼
 resume   status block + pack wrapped as untrusted data + changes since the pack
```

| Module | Role |
|---|---|
| `scan`, `policy`, `safepath`, `config` | file discovery, allowlist and deny rules, confined reads, layered configuration |
| `redact`, `injection`, `gitrun` | secrets and personal data, prompt-injection heuristics, hardened read-only git |
| `extract/`, `handoff` | items from Markdown, manifests and git; the session handoff |
| `budget`, `tokens`, `render`, `store`, `consent` | tiers and budget, calibrated token estimate, Markdown, storage, approvals |
| `verify`, `schema`, `resume` | verification and restore |
| `setup`, `autoresume` | the CLAUDE.md block, the SessionStart hook and its digest |

The JSON pack is authoritative, and the Markdown is rendered from it, so `verify` can re-render
it and compare. A published [JSON Schema](schema/context-pack-v1.schema.json) lets other tools
validate packs. The format is described in
[skills/context-bridge/references/format.md](skills/context-bridge/references/format.md). The
Markdown file is portable: you can paste it into another assistant.

## Security and privacy

- Only allowlisted files inside the project are read. There are no symlink escapes and no special
  files, and size limits apply. Deny roots from your user configuration are checked before anything
  is read.
- `.env` files, keys and credentials are never opened. Secrets and personal data are redacted, and
  files with a private key are excluded.
- Approvals are stored outside the project, so a repository cannot ship its own approval.
- Pack content is data, not instructions. It is escaped so that it cannot close its wrapper, and
  instruction-like text is flagged.
- git runs read-only with hardened options. It does not run at all if the repository's own
  configuration could start programs.
- The scripts make no network calls, collect no telemetry and call no language model.

To report a vulnerability, see [SECURITY.md](SECURITY.md). The threat model is in
[skills/context-bridge/references/security.md](skills/context-bridge/references/security.md).

## Quality

- **Context Quality Score:** five synthetic reference projects with known ground truth measure
  what survives compression at budgets from 500 to 4000 tokens. In the default mode every critical
  item survives at every budget. At the reference budgets the score is 100 for the small projects
  (2000 tokens) and 97.1 for the large one (4000 tokens).
- **Token counts:** they use an estimate calibrated against real Claude token counts. In
  leave-one-out validation it is off by 4.3 % on average and by at most 10.2 %.

See [docs/quality.md](docs/quality.md).

## Limitations

- Extraction is selective and lexical. Text under headings it does not recognise is not packed,
  and it is not reported as lost either.
- Handoff entries from the conversation cannot be checked against files.
- Token counts are estimates, calibrated for Claude's tokenizer on English and German text.
- Windows is tested in CI, but not yet with Claude Code itself. The skill and the hook were tested
  end to end in headless Claude Code sessions on macOS.

The full list is in [docs/limitations.md](docs/limitations.md).

## Contributing

Bug reports, ideas and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
and the [Code of Conduct](CODE_OF_CONDUCT.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE).
