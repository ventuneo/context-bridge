# Installing, updating and removing Context Bridge

Context Bridge is distributed only through its GitHub repository. There is no package on PyPI and
no entry in a plugin marketplace. A Claude Code skill is a folder. Installing Context Bridge means
putting the folder `skills/context-bridge` where Claude Code looks for skills.

## Requirements

- Python 3.11 or newer, available as `python3` (`python3 --version`)
- Claude Code
- git, to clone the repository (and, optionally, for repository information in packs)
- macOS or Linux. Windows is not supported yet.

## Install for your user account (all projects)

1. Clone a release tag. Any folder works; the examples use `~/.local/share/context-bridge`:

   ```sh
   git clone --branch v0.1.0 --depth 1 https://github.com/ventuneo/context-bridge.git ~/.local/share/context-bridge
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
   # context-bridge 0.1.0
   ```

4. Start a new Claude Code session and ask "What does the context-bridge skill do?" or type
   `/context-bridge`. Skills are loaded when a session starts.

Nothing else is changed: no settings, no CLAUDE.md, no hooks. Use
[`/context-bridge setup`](setup.md) if you want those.

## Install for one project (shared with your team)

To give everyone who works on a project the skill, copy the folder into the project. Copy it
rather than linking it, because a link into your home folder would not exist on other machines.

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/ventuneo/context-bridge.git /tmp/context-bridge
mkdir -p .claude/skills
cp -R /tmp/context-bridge/skills/context-bridge .claude/skills/
rm -rf /tmp/context-bridge
```

Commit `.claude/skills/context-bridge` so that the team gets the same version. Claude Code loads
project skills when a session starts in that project. Do not install the same skill both per user
and per project.

## Check what you install

- **Pin a version.** Clone a tag (`--branch v0.1.0`), not the default branch. The release notes
  name the commit of each tag:

  ```sh
  git -C ~/.local/share/context-bridge rev-parse HEAD
  ```

- **Read what the skill may run.** The `allowed-tools` line in
  [`skills/context-bridge/SKILL.md`](../skills/context-bridge/SKILL.md) lists the only commands the
  skill runs without asking: `python3 -I …/scripts/cb.py` with `scan`, `pack`, `verify`, `resume`
  and the read-only `setup` actions. `setup apply` and `setup undo` always ask.
- **Run the tests**, if you like. They need only Python:

  ```sh
  cd ~/.local/share/context-bridge && python3 -m unittest discover -s tests
  ```

## Update

Read the [changelog](../CHANGELOG.md) first, then switch the clone to the new tag:

```sh
git -C ~/.local/share/context-bridge fetch --depth 1 origin tag v0.2.0
git -C ~/.local/share/context-bridge checkout v0.2.0
python3 -I ~/.claude/skills/context-bridge/scripts/cb.py --version
```

Start a new Claude Code session afterwards. In a project that uses the integration, run
`cb.py setup status --root .` to see whether the CLAUDE.md block is current. Packs written by an
older version are still checked. If `verify` reports `renderer_changed` or another format, create a
new pack.

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

   Use `--target project` or `--target local` for project files, from that project's folder.
   `cb setup status --root .` shows what is still installed.

2. **Remove the skill and the clone:**

   ```sh
   rm ~/.claude/skills/context-bridge
   rm -rf ~/.local/share/context-bridge
   ```

   For a project install, remove `.claude/skills/context-bridge` from the project.

3. **Remove your data**, if you want to. These folders are not removed automatically:

   | Path | Contains |
   |---|---|
   | `~/.local/state/context-bridge/` (or `$XDG_STATE_HOME/context-bridge/`) | approvals of sources and the backups made by `setup`. Remove it only after step 1. |
   | `~/.config/context-bridge/config.toml` | your settings, such as deny roots and hook options |
   | `<project>/.context-bridge/` | the packs of that project; the folder is ignored by git |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `context-bridge requires Python 3.11 or newer` | `python3` on your PATH is older; install a newer Python and make it the first `python3` |
| The skill does not appear in Claude Code | start a new session; check that `~/.claude/skills/context-bridge/SKILL.md` exists through the link |
| Every session start shows a hook error after uninstalling | the hook was not undone: run step 1 with a fresh clone, or remove the entry that calls `cb.py session-start` from your `settings.json` |
| `scan` says the root lies inside a denied location | the folder is in `deny_roots` of your user configuration; this is intended |
