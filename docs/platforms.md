# Platforms

Context Bridge runs on macOS, Linux, Windows 10 and 11, and WSL 2, with Python 3.11 or newer. This
page lists what differs between them and how each platform is tested. Installation commands are in
[install.md](install.md).

## At a glance

| | macOS, Linux | Windows | WSL 2 |
|---|---|---|---|
| Python command | `python3` | `python` or `py -3` | `python3` |
| Skill installed with | a symbolic link | a directory junction | a symbolic link |
| Claude Code folder | `~/.claude` | `%USERPROFILE%\.claude` | `~/.claude` inside WSL |
| Approvals and setup backups | `~/.local/state/context-bridge` | `%LOCALAPPDATA%\context-bridge` | as on Linux |
| User configuration | `~/.config/context-bridge/config.toml` | `%APPDATA%\context-bridge\config.toml` | as on Linux |
| SessionStart hook | shell form: `python3 -I … session-start` | exec form: Python by its full path, no shell | as on Linux |
| Private files | modes 0700 and 0600 | the access rules of their folder | modes, except on Windows drives |
| Tested | in CI; real Claude Code sessions on macOS | in CI, without Claude Code | not on a real installation |

`XDG_STATE_HOME` and `XDG_CONFIG_HOME` take precedence on every system.

## Windows

- **Home folder.** Context Bridge uses `%USERPROFILE%`, the folder Claude Code uses. Git Bash can
  set `HOME` to a POSIX-style path that native programs cannot open; on Windows it is ignored.
- **Python.** `python3` is usually missing on Windows. The skill runs `python -I` or `py -3 -I`.
  The hook stores the full path of the Python that ran `setup`.
- **The hook.** Claude Code runs a hook that is written as one command line in Git Bash, or in
  PowerShell when Git Bash is not installed, and a quoted program path works in only one of them.
  On Windows the hook is therefore written in exec form (`command` plus `args`, Claude Code 2.1.139
  or newer), which starts Python without a shell. On macOS, Linux and WSL the hook keeps the shell
  form of 0.1, so existing installations stay current.
- **The skill's commands.** `allowed-tools` pre-approves the Windows forms for the Bash tool (Git
  Bash) and for the PowerShell tool. Windows PowerShell 5.1 drops the double quotes inside
  arguments, so `--handoff-json` breaks there; the skill then writes the handoff with the Write tool
  to `.context-bridge/handoff.json` and passes `--handoff`.
- **File names.** A path from a pack or a configuration is refused when one of its parts:
  - is a device name such as `CON`, `NUL` or `COM1`, also with an extension;
  - contains a character that Windows forbids, or a `:`, which would name an alternate data stream;
  - ends with a dot or a space, which Windows removes.

  Windows would otherwise open a device, a hidden stream or a different file.
- **Links.** Symbolic links and directory junctions count as links. Context Bridge never follows
  them out of the project and never stores packs through them. Other reparse points, such as
  OneDrive placeholders, are ordinary files.
- **Case.** Deny roots and approvals compare paths regardless of case and of the slash direction.
- **Permissions.** Windows has no POSIX permission bits. Files that Context Bridge writes get the
  access rules of their folder; in your user profile, only you can read them.
- **Replacing files.** A search indexer or a virus scanner can hold a file for a moment, so a write
  retries briefly before it fails.
- **Text.** Output is UTF-8, also in pipes, for which Windows would otherwise use the ANSI code
  page; hook and handoff input is read as UTF-8. Files with CRLF line endings, as Git for Windows
  often checks them out, give the same items as files with LF. `setup` keeps the line endings of
  the CLAUDE.md it changes.

## WSL 2

Inside WSL, Context Bridge is a Linux program: install it and run Claude Code inside WSL. On Windows
drives such as `/mnt/c`, `chmod` usually has no effect. `pack` checks whether the permissions of
`.context-bridge/` took effect and warns if they did not, with a hint for WSL. Keep projects in the
Linux file system, or mount Windows drives with the `metadata` option.

## How it is tested

- **CI** runs the whole test job on Linux, macOS and Windows with Python 3.11 to 3.15:
  - the unit and integration tests;
  - the quality gates and the token calibration check;
  - a fresh installation (`tools/install_smoke.py`, on Windows with a directory junction and the
    exec-form hook);
  - the JSON Schema cross-check and the privacy guard.

  Every step runs in bash, on Windows in Git Bash, so that a step stops at its first failing
  command.
- **Simulated Windows behaviour.** The platform layer (`scripts/context_bridge/compat.py`) takes the
  platform as a parameter. Tests therefore check the Windows decisions on every system: folders,
  unsafe names, junctions, path keys, retries and the hook entry. `CB_TEST_NO_SYMLINKS=1` simulates
  Windows without Developer Mode, where the tests that create symbolic links are skipped.
- **Checked by hand for 0.2.0:**
  - the test suite and the tools under a Latin-1 and a Windows code page (CP1251) with Python 3.11,
    where text input and output without an explicit encoding would fail;
  - scan, pack, verify and resume on a FAT32 volume, which has no POSIX permissions and gets a
    Windows-like git configuration;
  - the test suite, the tools and a fresh installation in Linux containers with Python 3.11 and
    3.15.
- **Not tested:**
  - Claude Code on Windows: whether the skill's commands need a permission prompt, and the hook in
    a real session;
  - WSL 2 on a real installation;
  - projects reached through `\\wsl$\` or a network drive;
  - Cygwin and MSYS2 builds of Python.
