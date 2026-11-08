# Context Bridge

Claude Code skill that extracts, compresses, verifies and restores project context.
Roadmap: `docs/roadmap.md`.

## Layout

| Path | Content |
|---|---|
| `skills/context-bridge/SKILL.md` | The Claude Code skill: workflows for scan, pack, verify, resume and the safety rules; `references/` holds handoff, format and security notes |
| `skills/context-bridge/scripts/cb.py` | Entry point, always run as `python3 -I cb.py …` |
| `skills/context-bridge/scripts/context_bridge/` | Package: safety core, `scan`, `pack` (model, extract/, budget, consent, store, render), `verify` (schema), `resume` |
| `schema/` | Published JSON Schema of the pack format (cross-checked by `tools/check_schema.py` in CI) |
| `quality/` | Context Quality Score: synthetic reference cases with ground truth, `evaluate.py`, `run.py`, `baseline.json` (see `docs/quality.md`) |
| `tests/` | `unittest` suite; `helpers.py` isolates HOME and guards the real home directory |
| `quality/tokens/` | Calibration samples, measured token counts and the scripts that measure and fit them |
| `examples/demo-project/` | Synthetic project used by the README demo, tests and the install smoke test |
| `docs/` | User and maintainer docs: install, setup, limitations, quality, release checklist |
| `tools/privacy_check.py` | Repository privacy guard used by `.githooks/` |

## Commands

```sh
python3 -m unittest discover -s tests
python3 -I skills/context-bridge/scripts/cb.py scan --root <dir> [--json]
python3 -I skills/context-bridge/scripts/cb.py pack --root <dir> [--approve] [--handoff -] [--dry-run]
python3 -I skills/context-bridge/scripts/cb.py verify|resume --root <dir> [--pack ID] [--json]
python3 -I skills/context-bridge/scripts/cb.py setup [status|preview|apply|undo-preview|undo] --target <scope> [--hook]
python3 -I quality/run.py [--check] [--details]      # Context Quality Score; --check = gates + baseline
python3 tools/privacy_check.py --all | --history
python3 -I quality/tokens/calibrate.py --check       # token estimate still fits its measurements
python3 -I tools/install_smoke.py                    # fresh install in a throwaway home (tests the last commit)
```

Local install for testing: symlink `~/.claude/skills/context-bridge` to `skills/context-bridge`.
`SKILL.md` may only run `python3 -I ${CLAUDE_SKILL_DIR}/scripts/cb.py ...` as a single plain command
(on Windows `python -I` or `py -3 -I`, in Bash or PowerShell; that is what `allowed-tools` permits);
pass the handoff with `--handoff-json`, never via pipe or heredoc.

## Rules

- Python 3.11+ and the standard library only. No runtime dependencies.
- Code, comments, docs and commit messages in English.
- No network access in the package. No LLM calls in the scripts; they stay deterministic.
- Never put personal data in versioned files: no absolute home paths, real names,
  personal e-mail addresses or private project names. Tests use synthetic data only;
  fake secrets are assembled at runtime.
- Every safety rule needs a negative test.
- Tests must never read the real home directory (enforced by the audit hook in `tests/helpers.py`).
