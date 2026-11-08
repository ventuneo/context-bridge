# Contributing to Context Bridge

Thank you for helping! Bug reports, documentation fixes, new reference cases and code are all
welcome. This guide explains how the project works and what a change needs before it can be merged.

## Ground rules

- **Python 3.11+ and the standard library only.** There are no runtime dependencies. Development
  tools (ruff, jsonschema) are used only in checks.
- **No network access and no language-model calls** in the skill's scripts. They stay
  deterministic: the same input gives the same pack.
- **Every safety rule has a negative test.** A rule without a test that tries to break it is not
  finished.
- **Synthetic data only.** Never commit real project content, personal data, private paths or real
  secrets, not even in tests. Fake secrets are assembled at runtime so that the repository never
  contains secret-looking strings.
- **English** for code, comments, documentation and commit messages.

## Development setup

```sh
git clone https://github.com/ventuneo/context-bridge.git
cd context-bridge
git config core.hooksPath .githooks          # privacy guard on every commit
```

The privacy guard blocks absolute home paths, personal e-mail addresses and every term listed in
the unversioned file `.git/info/private-terms`, one term per line. Put names and project names
there that must never be committed.

To try your working copy in Claude Code, link it as your skill:

```sh
ln -s "$PWD/skills/context-bridge" ~/.claude/skills/context-bridge
```

The repository's [CLAUDE.md](CLAUDE.md) describes the layout for assistants.

## Checks

CI runs all of them. Run them locally before you open a pull request:

```sh
python3 -W error -m unittest discover -s tests       # unit and integration tests
python3 -I quality/run.py --check                     # Context Quality Score gates and baseline
python3 -I quality/tokens/calibrate.py --check        # token estimate still matches its measurements
python3 -I tools/install_smoke.py                     # fresh install in a throwaway home folder
python3 tools/privacy_check.py --all                  # tracked files
python3 tools/privacy_check.py --history              # the whole history
ruff check . && ruff format --check .                 # ruff 0.17.4
```

The JSON Schema cross-check needs one development dependency:

```sh
python3 -m pip install "jsonschema==4.23.0" && python3 tools/check_schema.py
```

Tests must never read your real home folder; `tests/helpers.py` enforces this with an audit hook.

## Changes that need extra care

- **Pack format.** Update `schema/context-pack-v1.schema.json`,
  `skills/context-bridge/references/format.md` and the changelog. A breaking change raises the major
  part of `schema_version`.
- **Quality cases and the baseline.** Update `quality/baseline.json` only on purpose, with
  `quality/run.py --update-baseline`, and explain the change in `docs/quality.md`.
- **Token estimate.** Recalibrate with the steps in
  [docs/quality.md](docs/quality.md#token-estimate). Measuring sends the samples to a model and
  costs a few cents. A new calibration gets a new `ESTIMATOR` name and a new baseline.
- **The skill (`SKILL.md`).** Keep `allowed-tools` limited to `python3 -I …/cb.py` commands.
  `setup apply` and `setup undo` must keep asking the user.

## Pull requests

- One topic per pull request, with tests.
- Add an entry under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for anything a user notices.
- Describe what changes for users and how you tested it.
- Bug reports and examples must use synthetic data: no real secrets, private paths or packs from
  private projects.

## Reporting security issues

Do not open a public issue. Follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
