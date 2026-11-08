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

## Release notes for v0.3.0

> **Context Bridge 0.3.0: smart extraction**
>
> Context Bridge now keeps project context that is not under the headings it knows. Text under
> unrecognised headings, such as meeting notes, wiki pages or "Background" sections, used to be
> dropped without a trace. Now it is sorted by its wording or kept as a note, and every pack says
> what happened to each heading.
>
> - **Sorted by wording:** statements such as "we decided …", "wir haben entschieden …", "the goal
>   is …", "TODO …", "wir müssen noch …" or a question go to decisions, goals, next steps, tasks or
>   open questions, marked `(inferred)`.
> - **Unclassified notes:** everything else is kept as a note in a new section. Notes are the first
>   to be left out when the budget is tight, and the coverage statement counts them, so nothing
>   disappears silently.
> - **Statements, not blobs:** short note lines count one by one; wrapped prose is split into
>   sentences, respecting abbreviations such as "z. B." and "e.g.". Licence, credits and
>   table-of-contents sections are skipped.
> - **Extraction report:** `pack` prints a one-line summary, `pack --sections` shows per file and
>   heading what was kept, merged, shortened, left out or skipped, and `pack --dry-run --sections`
>   previews it without writing anything.
> - **Measured:** the Context Quality Score gains a metric for source coverage, the share of the
>   readable source text that ends up in items. On a new reference case of unstructured German and
>   English notes the score rose from 9.1 to 100 and source coverage from 5 % to 95 %; on the large
>   reference project source coverage rose from 40 % to 100 %. No score of the earlier cases changed.
> - **Same guarantees:** every item still names its file and line range and is re-derived by
>   `verify`; redaction, prompt-injection checks and token budgets apply to the new items too.
>
> **Compatibility:** packs now use schema 1.1. Packs written by 0.1 and 0.2 still verify; packs
> written by 0.3 need 0.3. A pack that was complete at its budget may now report PARTIAL coverage,
> because more text is extracted.
>
> **Known limitations:** sorting by wording is a heuristic for English and German only. A sentence
> that reports someone else's decision still counts as a decision, and a decision phrased without the
> known words stays an unclassified note. Statements are found by line length and punctuation.
> Checklist templates and milestone tables are still read as open tasks. Not tested yet: Claude Code
> itself on Windows, and WSL 2 on a real installation. Details are in docs/limitations.md and
> docs/quality.md.
>
> **Update:** check out the new tag in your clone (docs/install.md, Update). CI runs on Linux, macOS
> and Windows with Python 3.11 to 3.15.
