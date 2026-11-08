#!/usr/bin/env python3
"""Smoke test of a fresh installation, done the way docs/install.md and docs/setup.md describe it.

Everything happens in a throwaway folder: HOME, the XDG folders and the git configuration point
into it, so neither your real home folder nor your Claude Code settings are read or changed.

1. A bare copy of the source repository serves as "GitHub". It gets two tags: an older commit
   (the installed release) and the commit under test (the update).
2. Install: shallow clone of the older tag, link the skill folder into ``$HOME/.claude/skills``,
   ``cb.py --version``.
3. Update to the newer tag with the documented ``git fetch``/``git checkout`` commands.
4. scan → pack → verify → resume on a copy of examples/demo-project (a git repository).
5. setup: the SessionStart hook and the global CLAUDE.md block (preview → apply → idempotent).
   The hook command from settings.json is run the way Claude Code runs it.
6. Uninstall: undo the hook and the block (files restored byte for byte), remove the link, the
   clone and the state folder, then check that the home folder is exactly as before.

    python3 -I tools/install_smoke.py [--source PATH_OR_URL] [--ref REF] [--python python3] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IDENTITY = {"GIT_AUTHOR_NAME": "Smoke Test", "GIT_AUTHOR_EMAIL": "smoke@example.com",
            "GIT_COMMITTER_NAME": "Smoke Test", "GIT_COMMITTER_EMAIL": "smoke@example.com"}  # fmt: skip
HANDOFF = {
    "goal": {"text": "Ship reminders before the summer holidays.", "status": "fact"},
    "next_steps": [{"text": "Write the reminder command and its tests.", "status": "fact"}],
    "open_questions": [{"text": "Should reminders also work by e-mail?", "status": "uncertain"}],
}
OLD_TAG, NEW_TAG = "smoke-installed", "smoke-update"


class SmokeFailure(Exception):
    pass


def tree(root: Path) -> dict[str, bytes]:
    """Every file below ``root`` (links as their target text), for exact before/after comparisons."""
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            files[str(path.relative_to(root))] = os.readlink(path).encode()
        elif path.is_file():
            files[str(path.relative_to(root))] = path.read_bytes()
    return files


class Smoke:
    def __init__(self, base: Path, python: str) -> None:
        self.base, self.python = base, python
        self.home = base / "home"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "CONTEXT_BRIDGE", "GIT_"))}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_STATE_HOME=str(self.home / ".local" / "state"),
            XDG_DATA_HOME=str(self.home / ".local" / "share"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            **IDENTITY,
        )
        self.clone = self.home / ".local" / "share" / "context-bridge"
        self.link = self.home / ".claude" / "skills" / "context-bridge"
        self.passed = 0

    # --- helpers ---------------------------------------------------------------------------
    def run(self, *cmd: str, cwd: Path | None = None, stdin: str | None = None, codes: tuple[int, ...] = (0,)):
        result = subprocess.run(cmd, cwd=cwd, env=self.env, input=stdin, capture_output=True, text=True, timeout=180)
        if result.returncode not in codes:
            raise SmokeFailure(f"{shlex.join(cmd)} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        return result

    def cb(self, *args: str, cwd: Path, codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
        return self.run(self.python, "-I", str(self.link / "scripts" / "cb.py"), *args, cwd=cwd, codes=codes)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            raise SmokeFailure(f"{name} {detail}".strip())
        self.passed += 1
        print(f"ok   {name}")

    def preview_id(self, *args: str, cwd: Path) -> tuple[str, dict]:
        data = json.loads(self.cb("setup", *args, "--json", cwd=cwd).stdout)
        return data.get("preview_id", ""), data

    # --- steps -----------------------------------------------------------------------------
    def prepare_home(self) -> dict[str, bytes]:
        claude = self.home / ".claude"
        claude.mkdir(parents=True)
        (claude / "CLAUDE.md").write_text("# My rules\n\n- Keep answers short.\n", encoding="utf-8")
        settings = {"theme": "dark", "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "true"}]}]}}
        (claude / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return tree(self.home)

    def publish(self, source: str, ref: str) -> tuple[str, str]:
        """A bare repository that plays GitHub, with the commit under test and its parent as two tags."""
        origin = self.base / "origin.git"
        if Path(source).is_dir():  # a working copy, possibly on a detached commit (as in CI)
            repo = source
            self.run("git", "init", "--quiet", "--bare", str(origin))
            self.run("git", "-C", str(origin), "config", "receive.shallowUpdate", "true")
        else:  # a URL: its tags and branches are enough
            self.run("git", "clone", "--quiet", "--bare", source, str(origin))
            repo = str(origin)
        new = self.run("git", "-C", repo, "rev-parse", f"{ref}^{{commit}}").stdout.strip()
        parent = self.run("git", "-C", repo, "rev-parse", "--verify", "--quiet", f"{new}^", codes=(0, 1))
        old = parent.stdout.strip() or new  # without a parent (shallow source) the update is a no-op
        if repo == source:
            self.run("git", "-C", repo, "push", "--quiet", f"file://{origin}",
                     f"{old}:refs/tags/{OLD_TAG}", f"{new}:refs/tags/{NEW_TAG}")  # fmt: skip
        else:
            self.run("git", "-C", repo, "tag", OLD_TAG, old)
            self.run("git", "-C", repo, "tag", NEW_TAG, new)
        return f"file://{origin}", new

    def install(self, url: str) -> None:
        self.run("git", "clone", "--quiet", "--branch", OLD_TAG, "--depth", "1", url, str(self.clone))
        self.link.parent.mkdir(parents=True, exist_ok=True)
        self.link.symlink_to(self.clone / "skills" / "context-bridge")
        version = self.cb("--version", cwd=self.base).stdout.strip()
        self.check("install: clone a tag and link the skill folder", version.startswith("context-bridge "), version)

    def update(self, new: str) -> None:
        self.run("git", "-C", str(self.clone), "fetch", "--quiet", "--depth", "1", "origin", "tag", NEW_TAG)
        self.run("git", "-C", str(self.clone), "checkout", "--quiet", NEW_TAG)
        head = self.run("git", "-C", str(self.clone), "rev-parse", "HEAD").stdout.strip()
        init = (self.clone / "skills/context-bridge/scripts/context_bridge/__init__.py").read_text(encoding="utf-8")
        expected = re.search(r'__version__ = "([^"]+)"', init).group(1)  # type: ignore[union-attr]
        version = self.cb("--version", cwd=self.base).stdout.strip()
        self.check("update: fetch and check out the newer tag", head == new and version == f"context-bridge {expected}",
                   f"{head[:12]} {version}")  # fmt: skip

    def use(self) -> Path:
        project = self.base / "projects" / "shelf"
        shutil.copytree(self.clone / "examples" / "demo-project", project)
        self.run("git", "init", "--quiet", "-b", "main", cwd=project)
        self.run("git", "add", "-A", cwd=project)
        self.run("git", "commit", "--quiet", "-m", "Lend and return books", cwd=project)

        out = self.cb("scan", "--root", ".", cwd=project).stdout
        self.check("scan: four sources, code excluded", "Included: 4 files" in out and "src/shelf/cli.py" in out)
        self.cb("pack", "--root", ".", "--approve", "--handoff-json", json.dumps(HANDOFF), cwd=project)
        store = project / ".context-bridge"
        modes = (stat.S_IMODE(store.stat().st_mode), stat.S_IMODE((store / "latest.json").stat().st_mode))
        ignored = self.run("git", "status", "--porcelain", cwd=project).stdout.strip() == ""
        self.check("pack: written privately and ignored by git", modes == (0o700, 0o600) and ignored, str(modes))
        out = self.cb("verify", "--root", ".", cwd=project).stdout
        self.check("verify: OK", "Result: OK" in out, out)
        out = self.cb("resume", "--root", ".", cwd=project).stdout
        wrapped = out.count('<context_bridge_pack trust="untrusted-data"') == 1 and "</context_bridge_pack>" in out
        self.check("resume: verified pack wrapped as untrusted data", wrapped and "Write the reminder command" in out)
        return project

    def setup(self, project: Path) -> None:
        self.cb("setup", "status", "--root", ".", cwd=project)
        pid, data = self.preview_id("preview", "--target", "global", "--hook", "--root", ".", cwd=project)
        self.check("setup: hook preview", data["action"] == "install" and '"timeout": 10' in data["diff"])
        self.cb("setup", "apply", "--target", "global", "--hook", "--confirm", pid, "--root", ".", cwd=project)
        settings = json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        kept = settings["theme"] == "dark" and settings["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == "true"
        ours = [h["command"] for e in settings["hooks"]["SessionStart"] for h in e["hooks"]]
        self.check("setup: hook installed, other settings kept", kept and len(ours) == 1)

        def hook(cwd: Path, source: str) -> str:  # as Claude Code runs it: the command, JSON on stdin
            event = {"cwd": str(cwd), "source": source, "hook_event_name": "SessionStart"}
            return self.run(*shlex.split(ours[0]), cwd=cwd, stdin=json.dumps(event)).stdout

        empty = self.base / "projects" / "empty"
        empty.mkdir(parents=True)
        digest = hook(project, "startup")
        self.check("hook: digest at startup", digest.startswith("Context Bridge (SessionStart): context pack verified"))
        self.check(
            "hook: silent after /clear and without a pack", hook(project, "clear") == hook(empty, "startup") == ""
        )

        pid, data = self.preview_id("preview", "--target", "global", "--root", ".", cwd=project)
        self.cb("setup", "apply", "--target", "global", "--confirm", pid, "--root", ".", cwd=project)
        claude_md = (self.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        block = "<!-- context-bridge:begin v1 -->" in claude_md and claude_md.startswith("# My rules")
        self.check("setup: CLAUDE.md block added after the existing rules", block and "run `resume`" not in claude_md)
        again = [self.preview_id("preview", "--target", "global", *h, "--root", ".", cwd=project)[1]["action"]
                 for h in ((), ("--hook",))]  # fmt: skip
        self.check("setup: a second run changes nothing", again == ["none", "none"], str(again))

    def uninstall(self, project: Path, before: dict[str, bytes]) -> None:
        for extra in (("--hook",), ()):
            pid, _ = self.preview_id("undo-preview", "--target", "global", *extra, "--root", ".", cwd=project)
            self.cb("setup", "undo", "--target", "global", *extra, "--confirm", pid, "--root", ".", cwd=project)
        claude = self.home / ".claude"
        restored = all(
            tree(self.home)[f".claude/{n}"] == before[f".claude/{n}"] for n in ("CLAUDE.md", "settings.json")
        )
        self.check("uninstall: setup undo restores both files byte for byte", restored)
        self.link.unlink()
        shutil.rmtree(self.clone)
        shutil.rmtree(self.home / ".local" / "state" / "context-bridge")  # approvals and setup backups
        self.check("uninstall: the home folder is exactly as before", tree(self.home) == before,
                   str(sorted(set(tree(self.home)) ^ set(before))))  # fmt: skip
        self.check("uninstall: no skill left", not (claude / "skills" / "context-bridge").exists())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=str(REPO), help="repository to install from (default: this one)")
    parser.add_argument("--ref", default="HEAD", help="commit or tag to test (default: HEAD of the source)")
    parser.add_argument("--python", default="python3", help="interpreter for cb.py (default: python3, as documented)")
    parser.add_argument("--keep", action="store_true", help="keep the throwaway folder for inspection")
    args = parser.parse_args()
    base = Path(tempfile.mkdtemp(prefix="cb-smoke-")).resolve()
    smoke = Smoke(base, args.python)
    try:
        before = smoke.prepare_home()
        url, new = smoke.publish(args.source, args.ref)
        smoke.install(url)
        smoke.update(new)
        project = smoke.use()
        smoke.setup(project)
        smoke.uninstall(project, before)
    except SmokeFailure as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep:
            print(f"kept: {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)
    print(f"install smoke test passed: {smoke.passed} checks, commit {new[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
