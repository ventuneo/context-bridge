## What changes

<!-- What does this change for users, and why? Link the issue if there is one. -->

## How it was tested

<!-- Commands you ran and anything you checked by hand. -->

## Checklist

- [ ] Tests cover the change; every new safety rule has a negative test.
- [ ] `python3 -W error -m unittest discover -s tests` and `python3 -I quality/run.py --check` pass.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] Only synthetic data: no real secrets, personal data or private paths.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` if users notice the change.
- [ ] Documentation is updated (README, docs, SKILL.md or references).
