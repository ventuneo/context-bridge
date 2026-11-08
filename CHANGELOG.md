# Changelog

All notable changes to Context Bridge are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0, a minor version may change
the command line or the pack format; such changes are listed under **Changed**.

## [Unreleased]

## [0.1.0] - 2026-11-08

First public release.

### Added

- `scan` lists the files a pack may use and why others are excluded. It applies:
  - an allowlist of documentation and manifests;
  - hard deny rules for secrets and keys;
  - deny roots from the user configuration;
  - size limits.

  It reports findings for secrets, personal data and prompt-injection patterns.
- `pack`:
  - extracts goals, constraints, decisions, next steps, state, open questions, tasks, commands and
    project facts from Markdown, manifests and git;
  - adds a session handoff (`--handoff-json` or `--handoff -`);
  - merges duplicates and fits the rendered pack into a token budget by tier;
  - reports dropped critical items as critical information loss (exit code 3);
  - states the coverage of every pack;
  - stores JSON and Markdown in `.context-bridge/`;
  - asks for approval of new sources.
- `verify` checks:
  - the schema, fingerprint and content hash, and re-renders the Markdown;
  - provenance: forged items in unchanged files are detected even with recomputed hashes;
  - safety, with a re-scan;
  - freshness: changed or missing sources, outdated items, repository progress, rewritten history,
    pack age.
- `resume` prints only verified packs, wrapped as untrusted data, with the changes since the pack.
- `setup` adds a marked block to a CLAUDE.md file and, optionally, the auto-resume SessionStart
  hook. Every change has a preview id, a backup and an exact undo.
- The auto-resume SessionStart hook loads a short, verified digest when a session starts, about 350
  tokens. It loads nothing without a pack and only a warning for a pack that fails verification.
- The Claude Code skill (`skills/context-bridge/SKILL.md`) has workflows for saving, restoring,
  verifying and setup, and references on the handoff, the pack format and security.
- A token estimate calibrated against real Claude token counts. In leave-one-out validation it is
  off by 4.3 % on average and by at most 10.2 %. Samples, measurements and scripts are in
  `quality/tokens/`.
- The Context Quality Score over five synthetic reference projects, with gates and a baseline.
- A JSON Schema of the pack format (`schema/context-pack-v1.schema.json`).
- Documentation: installation, setup, limitations, quality and the release checklist, plus a
  contributing guide, a security policy and a code of conduct.
- Continuous integration on Linux and macOS with Python 3.11 to 3.15, including a smoke test of a
  fresh installation.

### Security

- Local only: no network access, no telemetry and no calls to language models.
- Approvals are stored outside the project, so a repository cannot ship its own approval.
- git runs read-only, and it is skipped when a repository's configuration could start programs.

[Unreleased]: https://github.com/ventuneo/context-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ventuneo/context-bridge/releases/tag/v0.1.0
