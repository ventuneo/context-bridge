# Security policy

Context Bridge reads project files and writes packs that assistants then read, so security
problems matter. Thank you for reporting them responsibly.

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | yes |
| 0.2.x and older | no, please update |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting instead: open
the repository's **Security** tab and choose **Report a vulnerability**. The report is visible only
to you and the maintainers.

Please include:

- the version (`cb.py --version`) or commit, your operating system and Python version;
- what an attacker controls (project files, a pack, commit messages, configuration) and what they
  achieve;
- steps to reproduce with **synthetic data**.

Do not include real secrets, personal data or packs from private projects.

This is a volunteer project. Reports are handled on a best-effort basis, and you will get an answer
in the advisory. Fixes are released as a patch version and credited in the changelog, unless you
prefer not to be named.

## Scope

In scope are ways for project content, a pack, a commit subject or a configuration file to make
Context Bridge:

- read files outside the approved sources, or inside a denied location, for example through a
  symbolic link, a directory junction or a Windows device name;
- write outside `.context-bridge/` or outside a confirmed `setup` target;
- put secrets or personal data into a pack;
- skip the approval of new sources;
- run programs, for example through git configuration;
- accept a forged or modified pack in `verify` or `resume`;
- let pack content escape its untrusted-data wrapper.

Out of scope:

- An assistant that follows instructions found in pack content despite the wrapper and the
  warnings. Please report such cases anyway: they help to improve the wording. This limit is
  documented.
- Attacks that require a modified Context Bridge installation or control over your user account.

## Design

The threat model and the protections are described in
[skills/context-bridge/references/security.md](skills/context-bridge/references/security.md).
Known limits, such as the unverifiable session handoff, are listed in
[docs/limitations.md](docs/limitations.md).
