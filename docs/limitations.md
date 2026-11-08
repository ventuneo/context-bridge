# Known limitations

Context Bridge 0.3 is an early release. This page lists what it does not do, or does only
approximately, so that you can judge its output. The [quality report](quality.md) has the
measurements behind the numbers.

## Token counts

The Python standard library has no tokenizer, so token counts are estimates. They are a weighted sum
of six text features, calibrated against real token counts (see
[Token estimate](quality.md#token-estimate)).

- **Calibrated for Claude's tokenizer.** Claude Haiku 5.5 and Opus 5.5 counted exactly the same
  tokens. Other vendors' tokenizers and other Claude generations may count differently.
- **Calibrated on English and German.** Other languages are estimated with the English weights.
  Text in scripts such as Chinese or Japanese is underestimated considerably, because each
  character is counted like an English letter. This was not measured. Heavy emoji use and long
  hexadecimal strings are less accurate too.
- **Accuracy.** On the 16 calibration samples the estimate is off by 4.3 % on average and by at
  most 10.2 % (leave-one-out). Pack budgets are therefore approximate, and by default the budget may
  be exceeded to keep critical items. The SessionStart hook uses an upper bound (the estimate plus
  11 %) so that its digest stays within its limit.
- **Fixed parts cost tokens.** The trust notice, the coverage line, the status line and the sources
  table of a pack take about 350 to 500 tokens. With budgets below about 1000, little room is left
  for items.

## Context extraction

- **Selective, not a summary.** Items come from:
  - sections under recognised headings in English and German, such as Goals, Constraints, Rules,
    Decisions, Next steps, Status, Open questions, Tasks and Commands;
  - `Key: value` lines such as `Goal:`, `Decision:` or `Status:`;
  - text under other headings ("Notes", "Background") and before the first heading (smart
    extraction, since 0.3);
  - project metadata from manifests and git.

  Code blocks other than commands, boilerplate sections (licence, credits, table of contents) and
  more than 60 statements from unrecognised sections per file are not extracted. The extraction
  report counts them, and the coverage statement of every pack says that extraction is selective.
- **Sorting by wording is a heuristic.** It knows few phrases, in English and German only: "we
  decided", "wir haben entschieden", "TODO", "wir müssen noch", "das Ziel ist", a question mark and
  similar. A sentence that reports someone else's decision still counts as a decision; a decision
  without such words stays an unclassified note. Quoted text and inline code do not count, and a
  question mark does not make a table row a question. These items are marked `(inferred)`, and
  unclassified notes are the first to be left out when the budget is tight.
- **Statements are found by line length and punctuation.** Short lines count as one statement each;
  wrapped prose is split at sentence ends, except after common abbreviations (z. B., e.g.) and
  ordinal numbers (1. Juli). Unusual wrapping can still split or join statements wrongly.
- **Lexical, not semantic.** Context Bridge copies statements; it does not rephrase, merge or judge
  them. Contradicting statements are all kept. Near-duplicates are merged only when their wording is
  very similar.
- **Only an allowlist of files is read:**
  - READMEs and agent rule files (`CLAUDE.md`, `AGENTS.md` and similar);
  - `docs/**/*.md`, ADR folders, changelogs and common manifests.

  Source code is counted but never read, so anything stated only in code is missing.
- **Size limits.** By default files over 256 KB are skipped, and at most 2 MB are read per project.
- **The session handoff cannot be verified.** Entries from the conversation are checked for format,
  secrets and instruction-like text, but not against files. They are marked `(unverified)`. Someone
  with write access to the pack could change such an entry and recompute every hash, and that would
  not be detected; a signature is planned for a later version.
- **Changed files hide forgeries.** For an unchanged file, every item must be re-derivable, which
  detects forged items. Once the file has changed, a forged item cannot be told apart from an
  outdated one; both are reported as outdated.
- **Prompt-injection detection is heuristic.** It knows common patterns in English and German, fake
  chat markup, hidden comments and invisible Unicode. It cannot catch every attempt. The main
  defence is that pack content is always presented as untrusted data.

## Platforms and integration

- **Windows is tested without Claude Code.** CI runs the test suite and a fresh installation on
  Windows with Python 3.11 to 3.15. Claude Code on Windows was not tested:
  - The skill's commands may need a permission prompt there. Whether they run without one depends
    on how Claude Code writes the skill folder into commands.
  - The SessionStart hook was started the way the Claude Code documentation describes its exec form,
    but not by Claude Code itself.
- **Windows PowerShell 5.1 and the handoff.** Without Git for Windows, Claude Code runs commands in
  PowerShell. Windows PowerShell 5.1 drops the double quotes inside arguments, which breaks
  `--handoff-json`. The skill then passes the handoff in a file instead.
- **No POSIX permissions on Windows.** There, `.context-bridge/`, approvals and setup backups are
  protected by the access rules of the folder they are in, not by file modes. In your user profile
  only you can read them. A project elsewhere, for example on another drive, keeps the rules of that
  drive, which may let other users of the computer read its packs.
- **Links on Windows.** Creating a symbolic link needs Developer Mode or administrator rights.
  Context Bridge treats symbolic links and directory junctions alike and never follows one out of
  the project.
- **WSL 2 was not tested on a real installation.** Inside WSL, Context Bridge follows the Linux
  rules, which CI tests. On a Windows drive (`/mnt/c/...`), file permissions usually have no effect,
  and `pack` warns about this. Projects opened from Windows through `\\wsl$\` were not tested.
- **The Python command.** On macOS, Linux and WSL the skill and the hook call `python3`, which must
  be Python 3.11 or newer; an older `python3` only prints an error. On Windows the skill calls
  `python` or `py -3`, and the hook starts the Python that ran `setup` by its full path.
- **Tested in headless sessions.** The skill and the SessionStart hook were tested end to end with
  `claude -p` on macOS. Interactive sessions use the same mechanisms, but no automated test covers
  them.
- **The hook answers startup and resume.** After `/clear` or a compaction it stays silent unless you
  configure otherwise. When a session is resumed, Claude Code adds the digest again only if it
  changed.
- **git can be skipped.** If a repository's own git configuration could start programs (fsmonitor,
  filters, a pager and similar), Context Bridge does not run git there and packs without repository
  information.
- **Approvals belong to a folder.** They are stored per real path. After you move a project, you
  approve its sources again.
- **The name.** Several unrelated projects are called "context-bridge". A different skill with the
  same name in `~/.claude/skills/` would collide with this one.
