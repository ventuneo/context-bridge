# Release checklist

Context Bridge is released only on GitHub: a tag, a GitHub release and the documented `git clone`.
There is no package upload and no plugin-marketplace entry.

## Before every release

- [ ] `main` is green in CI: tests on Linux, macOS and Windows with Python 3.11 to 3.15, lint, the
      install smoke test.
- [ ] The branch protection of `main` requires every CI job: 15 test jobs (three systems, five
      Python versions) and lint. Add new jobs there when the matrix grows.
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
- [ ] If a Windows computer is available, the same in Claude Code on Windows, with Git for Windows
      and, if possible, without it (PowerShell). Note in the release notes whether this was done.

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

## Release notes for v0.3.1

> **Context Bridge 0.3.1: fixes for smart extraction**
>
> Two cases where smart extraction sorted text wrongly, found when Context Bridge packed its own
> documentation:
>
> - **Quoted examples are not statements.** A line that quotes "we decided" or "TODO", in quotation
>   marks or as inline code, is no longer a decision or a task. Apostrophes as in "we've" or "don't"
>   never start a quotation, and a decision that only quotes a name is still a decision.
> - **Questions in tables are labels.** A Markdown table row is no longer an open question only
>   because its cells end with a question mark, as in a comparison table with a "Question" row. Cue
>   phrases in table rows still count.
>
> Nothing else changed: all 48 runs of the Context Quality Score match 0.3.0 exactly (score,
> critical items and source coverage).
>
> **Known limitation:** short forms such as "we've agreed" are not recognised as decisions yet;
> "we've decided to …" is.
>
> **Update:** check out the new tag in your clone (docs/install.md, Update). CI runs on Linux, macOS
> and Windows with Python 3.11 to 3.15.
