#!/usr/bin/env python3
"""Repository privacy guard.

Keeps personal data out of versioned files and git history:

* absolute home-directory paths (``/Users/<name>``, ``/home/<name>``, ``C:\\Users\\<name>``)
* e-mail addresses other than example domains and no-reply addresses
* private terms from a local, unversioned list (``.git/info/private-terms``)
* author/committer identities that do not use a no-reply address

Usage::

    privacy_check.py --staged          # pre-commit hook: staged files + identity
    privacy_check.py --message FILE    # commit-msg hook
    privacy_check.py --all             # every tracked file in the index
    privacy_check.py --history         # every object and commit in the repository

Exit codes: 0 clean, 1 findings, 2 error.
Standalone on purpose: it must not import project code.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_HOME_NAMES = frozenset(
    {"alice", "bob", "carol", "example", "runner", "user", "username", "shared", "you", "name", "me"}
)
HOME_PATH_RE = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)([A-Za-z0-9._-]+)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
ALLOWED_EMAILS = frozenset({"noreply@anthropic.com", "git@github.com"})
NOREPLY_SUFFIX = "@users.noreply.github.com"
RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost")  # RFC 2606


@dataclass(frozen=True)
class Finding:
    where: str
    line: int
    reason: str

    def __str__(self) -> str:
        loc = f"{self.where}:{self.line}" if self.line else self.where
        return f"{loc}: {self.reason}"


def git(*args: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", "--no-pager", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def load_private_terms() -> list[str]:
    try:
        path = Path(git("rev-parse", "--git-path", "info/private-terms").decode().strip())
    except RuntimeError:
        return []
    if not path.is_file():
        return []
    terms = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            terms.append(term.casefold())
    return terms


def email_allowed(address: str) -> bool:
    address = address.casefold()
    if address in ALLOWED_EMAILS or address.endswith(NOREPLY_SUFFIX):
        return True
    domain = address.rsplit("@", 1)[-1]
    return domain in ALLOWED_EMAIL_DOMAINS or domain.endswith(RESERVED_TLDS)


def check_text(text: str, where: str, terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in HOME_PATH_RE.finditer(line):
            if match.group(1).casefold() not in ALLOWED_HOME_NAMES:
                findings.append(Finding(where, lineno, "absolute home path"))
        for match in EMAIL_RE.finditer(line):
            if not email_allowed(match.group(0)):
                findings.append(Finding(where, lineno, "e-mail address"))
        folded = line.casefold()
        for term in terms:
            if term in folded:
                findings.append(Finding(where, lineno, f"private term '{term}'"))
    return findings


def check_identity(terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for var in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        ident = git("var", var).decode(errors="replace").strip()
        match = re.match(r"(.*) <([^>]*)>", ident)
        name, email = (match.group(1), match.group(2)) if match else (ident, "")
        if not email.casefold().endswith(NOREPLY_SUFFIX):
            hint = "identity must use a GitHub no-reply e-mail (git config --local user.email)"
            findings.append(Finding(var, 0, hint))
        findings += [Finding(var, 0, f"private term '{t}' in name") for t in terms if t in name.casefold()]
    return findings


def check_staged(terms: list[str]) -> list[Finding]:
    findings = check_identity(terms)
    names = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").split(b"\0")
    for raw in filter(None, names):
        path = raw.decode(errors="replace")
        findings += check_text(path, f"{path} (file name)", terms)
        findings += check_text(git("show", f":{path}").decode(errors="replace"), path, terms)
    return findings


def check_all(terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for raw in filter(None, git("ls-files", "-z").split(b"\0")):
        path = raw.decode(errors="replace")
        findings += check_text(path, f"{path} (file name)", terms)
        findings += check_text(git("show", f":{path}").decode(errors="replace"), path, terms)
    return findings


def check_message(path: Path, terms: list[str]) -> list[Finding]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    return check_text("\n".join(lines), "commit message", terms)


def check_history(terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    log = git("log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e").decode(errors="replace")
    for record in filter(None, (r.strip("\n") for r in log.split("\x1e"))):
        sha, an, ae, cn, ce, body = record.split("\x00", 5)
        where = f"commit {sha[:10]}"
        for email in (ae, ce):
            if not email_allowed(email):
                findings.append(Finding(where, 0, "author/committer e-mail is not a no-reply address"))
        findings += check_text(f"{an}\n{cn}\n{body}", where, terms)
    listing = git("cat-file", "--batch-all-objects", "--batch-check=%(objecttype) %(objectname)").decode()
    blobs = [line.split()[1] for line in listing.splitlines() if line.startswith("blob ")]
    if blobs:
        data = git("cat-file", "--batch", input_bytes=("\n".join(blobs) + "\n").encode())
        pos = 0
        while pos < len(data):
            header_end = data.index(b"\n", pos)
            oid, _type, size = data[pos:header_end].decode().split()
            start = header_end + 1
            content = data[start : start + int(size)]
            findings += check_text(content.decode(errors="replace"), f"blob {oid[:10]}", terms)
            pos = start + int(size) + 1
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--message", type=Path)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--history", action="store_true")
    args = parser.parse_args(argv)
    try:
        terms = load_private_terms()
        if args.staged:
            findings = check_staged(terms)
        elif args.message:
            findings = check_message(args.message, terms)
        elif args.all:
            findings = check_all(terms)
        else:
            findings = check_history(terms)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"privacy_check: error: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("privacy_check: blocked – personal data found:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
