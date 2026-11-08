# Release checklist

Context Bridge is released only on GitHub: a tag, a GitHub release and the documented `git clone`.
There is no package upload and no plugin-marketplace entry.

## Before every release

- [ ] `main` is green in CI: tests on Linux and macOS with Python 3.11 to 3.15, lint, the install
      smoke test.
- [ ] Local checks pass:

      python3 -W error -m unittest discover -s tests
      python3 -I quality/run.py --check
      python3 -I quality/tokens/calibrate.py --check
      python3 -I tools/install_smoke.py
      python3 tools/privacy_check.py --all && python3 tools/privacy_check.py --history
      gitleaks git --redact --log-opts="--all" . && gitleaks dir --redact .
      actionlint
      ruff check . && ruff format --check .

- [ ] The version is the same in `pyproject.toml` and `skills/context-bridge/scripts/context_bridge/__init__.py`
      (`tests/test_release.py` checks this).
- [ ] `CHANGELOG.md`: the release section has its date, `[Unreleased]` is empty, and the links at the
      bottom name the new tag.
- [ ] README and `docs/install.md` clone the new tag.
- [ ] `docs/limitations.md` and `docs/quality.md` describe the current state.
- [ ] Check by hand in an interactive Claude Code session:
  - "Save the context" in a test project;
  - "Where were we?" in a new session;
  - `/context-bridge setup` up to the preview.

## First publication (v0.1.0)

1. Create the repository as **private** first:
   `gh repo create ventuneo/context-bridge --private --source . --remote origin --description "Verified, source-anchored context packs for Claude Code"`
2. In the repository settings:
   - enable **private vulnerability reporting** (Security);
   - allow **reported content** (Moderation options);
   - turn off the wiki and projects;
   - add the topics `claude-code`, `claude-skill`, `ai-assistant`, `context`, `developer-tools`;
   - protect `main`: require the CI checks and disallow force pushes.
3. `git push -u origin main` and wait for CI.
4. Check on GitHub:
   - the README renders and its badges work;
   - the license is detected as MIT;
   - the community profile is complete;
   - no unexpected files are listed.
5. Tag and release:

       git tag -a v0.1.0 -m "Context Bridge 0.1.0"
       git push origin v0.1.0
       gh release create v0.1.0 --title "Context Bridge 0.1.0" --notes-file <release notes>

6. Run the smoke test against GitHub:
   `python3 -I tools/install_smoke.py --source https://github.com/ventuneo/context-bridge.git --ref v0.1.0`
7. Make the repository **public** (Settings, General, Danger Zone, Change visibility).

## Later releases

1. Choose the version (SemVer). Before 1.0, a minor version may change the command line or the pack
   format; list such changes under **Changed** in the changelog.
2. Update the version, the changelog section and the tag in the install commands.
3. Run the checks above, then tag, push the tag and create the release.
4. Run the smoke test against the new tag.

## Release notes for v0.1.0 (proposal)

> **Context Bridge 0.1.0: first public release**
>
> Context Bridge is a Claude Code skill that saves where a project stands as a small,
> source-anchored context pack. It checks the pack against the current files and restores it in a
> new session.
>
> - `scan`, `pack`, `verify` and `resume`, local only, with the Python standard library
> - every item tied to its file, line range and checksum; session notes marked `(unverified)`
> - honest coverage: a pack never claims to be complete, and dropped critical items are reported
> - `/context-bridge setup`: an optional CLAUDE.md block and an optional SessionStart hook that loads
>   a verified digest of about 350 tokens, with preview, backup and undo
> - a token estimate calibrated against real Claude token counts, off by 4.3 % on average
>
> Install: see the README (`git clone` of the tag and a symbolic link). Supported on macOS and Linux
> with Python 3.11+. Known limitations: docs/limitations.md.
