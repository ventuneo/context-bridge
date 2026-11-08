# Installing, updating and removing Context Bridge

Context Bridge is distributed only through its GitHub repository. There is no package on PyPI and
no entry in a plugin marketplace. A Claude Code skill is a folder. Installing Context Bridge means
putting the folder `skills/context-bridge` where Claude Code looks for skills.

## Requirements

- Python 3.11 or newer. On macOS, Linux and WSL it must be available as `python3`
  (`python3 --version`); on Windows as `python` or through the `py` launcher (`py -3 --version`).
- Claude Code. On Windows, the optional SessionStart hook needs Claude Code 2.1.139 or newer.
- git, to clone the repository (and, optionally, for repository information in packs)
- macOS, Linux, Windows 10 or 11, or WSL 2. [Platforms](platforms.md) describes what differs
  between them.

## Install for your user account (all projects)

### macOS and Linux

1. Clone a release tag. Any folder works; the examples use `~/.local/share/context-bridge`:

   ```sh
   git clone --branch v0.3.0 --depth 1 https://github.com/ventuneo/context-bridge.git ~/.local/share/context-bridge
   ```

2. Link the skill folder into your personal skills folder:

   ```sh
   mkdir -p ~/.claude/skills
   ln -s ~/.local/share/context-bridge/skills/context-bridge ~/.claude/skills/context-bridge
   ```

   A symbolic link keeps a single copy. An update of the clone updates the skill, and the
   optional SessionStart hook keeps working because its path does not change.

3. Check the installation:

   ```sh
   python3 -I ~/.claude/skills/context-bridge/scripts/cb.py --version
   # context-bridge 0.3.0
   ```

4. Start a new Claude Code session and ask "What does the context-bridge skill do?" or type
   `/context-bridge`. Skills are loaded when a session starts.

Nothing else is changed: no settings, no CLAUDE.md, no hooks. Use
[`/context-bridge setup`](setup.md) if you want those.

### Windows

Run the commands in PowerShell. The examples clone into `%LOCALAPPDATA%\Programs\context-bridge`.

1. Clone a release tag:

   ```powershell
   git clone --branch v0.3.0 --depth 1 https://github.com/ventuneo/context-bridge.git "$env:LOCALAPPDATA\Programs\context-bridge"
   ```

2. Link the skill folder into your personal skills folder with a directory junction. Unlike a
   symbolic link, a junction needs neither administrator rights nor Developer Mode:

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
   New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\context-bridge" -Target "$env:LOCALAPPDATA\Programs\context-bridge\skills\context-bridge"
   ```

3. Check the installation:

   ```powershell
   python -I "$env:USERPROFILE\.claude\skills\context-bridge\scripts\cb.py" --version
   # context-bridge 0.3.0
   ```

   If `python` is not found or opens the Microsoft Store, use the launcher instead:
   `py -3 -I "$env:USERPROFILE\.claude\skills\context-bridge\scripts\cb.py" --version`.

4. Start a new Claude Code session, as on macOS.

Claude Code on Windows runs commands in Git Bash when Git for Windows is installed and in
PowerShell otherwise. The skill's commands are pre-approved for both. Approvals and setup backups
are stored in `%LOCALAPPDATA%\context-bridge`, your settings in `%APPDATA%\context-bridge`.

### WSL 2

Inside WSL, Context Bridge is a Linux program. Install it with the macOS and Linux commands in your
Linux home folder, and run Claude Code inside WSL. Claude Code for Windows uses
`%USERPROFILE%\.claude` and needs the Windows installation. The two installations share no skills,
settings or approvals.

Keep projects in the Linux file system, for example `~/projects`, rather than under `/mnt/c`.
Windows drives mounted in WSL ignore file permissions unless they are mounted with the `metadata`
option. On such a drive, `pack` warns that other users of the computer may be able to read
`.context-bridge/`. Files checked out by Git for Windows often have CRLF line endings; Context
Bridge reads them like files with LF.

## Install for one project (shared with your team)

To give everyone who works on a project the skill, copy the folder into the project. Copy it
rather than linking it, because a link into your home folder would not exist on other machines.

```sh
git clone --branch v0.3.0 --depth 1 https://github.com/ventuneo/context-bridge.git /tmp/context-bridge
mkdir -p .claude/skills
cp -R /tmp/context-bridge/skills/context-bridge .claude/skills/
rm -rf /tmp/context-bridge
```

On Windows, in PowerShell:

```powershell
git clone --branch v0.3.0 --depth 1 https://github.com/ventuneo/context-bridge.git "$env:TEMP\context-bridge"
New-Item -ItemType Directory -Force .claude\skills | Out-Null
Copy-Item -Recurse "$env:TEMP\context-bridge\skills\context-bridge" .claude\skills\
Remove-Item -Recurse -Force "$env:TEMP\context-bridge"
```

Commit `.claude/skills/context-bridge` so that the team gets the same version. Claude Code loads
project skills when a session starts in that project. Do not install the same skill both per user
and per project.

## Check what you install

- **Pin a version.** Clone a tag (`--branch v0.3.0`), not the default branch. The release notes
  name the commit of each tag:

  ```sh
  git -C ~/.local/share/context-bridge rev-parse HEAD
  ```

- **Read what the skill may run.** The `allowed-tools` line in
  [`skills/context-bridge/SKILL.md`](../skills/context-bridge/SKILL.md) lists the only commands the
  skill runs without asking: `python3 -I …/scripts/cb.py` (on Windows `python -I` or `py -3 -I`, in
  Bash or PowerShell) with `scan`, `pack`, `verify`, `resume` and the read-only `setup` actions.
  `setup apply` and `setup undo` always ask.
- **Run the tests**, if you like. They need only Python:

  ```sh
  cd ~/.local/share/context-bridge && python3 -m unittest discover -s tests
  ```

  On Windows: `cd "$env:LOCALAPPDATA\Programs\context-bridge"; python -m unittest discover -s tests`.

## Update

Read the [changelog](../CHANGELOG.md) first, then switch the clone to the new tag:

```sh
git -C ~/.local/share/context-bridge fetch --depth 1 origin tag v0.3.0
git -C ~/.local/share/context-bridge checkout v0.3.0
python3 -I ~/.claude/skills/context-bridge/scripts/cb.py --version
```

On Windows, in PowerShell:

```powershell
git -C "$env:LOCALAPPDATA\Programs\context-bridge" fetch --depth 1 origin tag v0.3.0
git -C "$env:LOCALAPPDATA\Programs\context-bridge" checkout v0.3.0
python -I "$env:USERPROFILE\.claude\skills\context-bridge\scripts\cb.py" --version
```

Start a new Claude Code session afterwards. In a project that uses the integration, run
`cb.py setup status --root .` to see whether the CLAUDE.md block is current. Packs written by an
older version are still checked. If `verify` reports `renderer_changed` or another format, create a
new pack.

On Windows, the SessionStart hook starts Python by its full path. After you remove that Python or
move to a new minor version, which installs into a new folder, run
`setup preview --target global --hook` again and apply it. It replaces the hook entry in place.

Project installs: copy the folder of the new version over the old one and commit it.

## Uninstall

Remove the integration first, then the files. Otherwise a SessionStart hook would still point to
a file that no longer exists.

1. **Undo the integration** (only if you used `setup`). For every target you set up, the hook
   (`--hook`) and the CLAUDE.md block, show the undo and then confirm it:

   ```sh
   cb() { python3 -I ~/.claude/skills/context-bridge/scripts/cb.py "$@"; }
   cb setup undo-preview --target global --hook --root .
   cb setup undo --target global --hook --confirm <id> --root .
   cb setup undo-preview --target global --root .
   cb setup undo --target global --confirm <id> --root .
   ```

   On Windows, define `cb` in PowerShell and run the same four commands:

   ```powershell
   function cb { python -I "$env:USERPROFILE\.claude\skills\context-bridge\scripts\cb.py" @args }
   ```

   Use `--target project` or `--target local` for project files, from that project's folder.
   `cb setup status --root .` shows what is still installed.

2. **Remove the skill and the clone:**

   ```sh
   rm ~/.claude/skills/context-bridge
   rm -rf ~/.local/share/context-bridge
   ```

   On Windows, `rmdir` removes the junction and leaves the folder it points to alone:

   ```powershell
   cmd /c rmdir "$env:USERPROFILE\.claude\skills\context-bridge"
   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\context-bridge"
   ```

   For a project install, remove `.claude/skills/context-bridge` from the project.

3. **Remove your data**, if you want to. These folders are not removed automatically:

   | macOS, Linux, WSL | Windows | Contains |
   |---|---|---|
   | `~/.local/state/context-bridge/` (or `$XDG_STATE_HOME/context-bridge/`) | `%LOCALAPPDATA%\context-bridge\` | approvals of sources and the backups made by `setup`. Remove it only after step 1. |
   | `~/.config/context-bridge/config.toml` | `%APPDATA%\context-bridge\config.toml` | your settings, such as deny roots and hook options |
   | `<project>/.context-bridge/` | the same | the packs of that project; the folder is ignored by git |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `context-bridge requires Python 3.11 or newer` | `python3` on your PATH is older; install a newer Python and make it the first `python3` |
| `python3` is not found (Windows) | Windows calls it `python` or `py -3`; use the Windows commands above. The skill does this by itself |
| `Python was not found; run without arguments to install from the Microsoft Store` | `python` is only the Store's placeholder: install Python, for example from python.org, or use `py -3` |
| The skill does not appear in Claude Code | start a new session; check that `~/.claude/skills/context-bridge/SKILL.md` exists through the link |
| Every session start shows a hook error after uninstalling | the hook was not undone: run step 1 with a fresh clone, or remove the entry that calls `cb.py session-start` from your `settings.json` |
| A session start shows a hook error after a Python update (Windows) | the hook starts the Python that ran `setup`: preview and apply the hook again, as described under [Update](#update) |
| `pack` warns that the file system ignores file permissions | the project is on a drive without POSIX permissions, such as a Windows drive in WSL: move it into the Linux file system or mount the drive with `metadata` |
| `scan` says the root lies inside a denied location | the folder is in `deny_roots` of your user configuration; this is intended |
