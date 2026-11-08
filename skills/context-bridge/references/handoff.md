# Session handoff

The handoff carries what was learned **in the conversation** and is not yet in the files:
decisions and their reasons, the current goal, the state, the next steps and open questions.
The project files are extracted by `pack` itself, so do not copy their content into the handoff.

## Fields

All fields are optional. An entry is either an object with `text` and `status`, or a plain
string. Plain strings carry no label, so they are marked `uncertain` and flagged `unlabeled`;
prefer objects.

| Field | Content | Pack section |
|---|---|---|
| `goal` | one entry: the goal of the current work | Goals |
| `status` | one entry: where the work stands | Current state |
| `state` | list: the same as `status`, for several statements | Current state |
| `done` | list: what was finished in this session | Current state |
| `constraints` | list: rules or limits agreed in the session | Constraints |
| `decisions` | list: `text`, `status` and optionally `reason` | Decisions |
| `next_steps` | list: concrete next actions | Next steps |
| `open_questions` | list: what is still unclear | Open questions |
| `files_touched` | list of project-relative paths | Current state |
| `author` | short name of the assistant, optional | source label |

## Statuses

- `fact`: established in the session (the user confirmed it, or it was observed, e.g. tests ran).
- `assumption`: taken as true without confirmation.
- `uncertain`: open, unclear or only possible.

Session entries are always shown as `(unverified)`: they have no source file to check against.

## Rules

- One statement per entry, at most 1000 characters; at most 50 entries per field.
- No secrets, tokens, passwords, personal data or absolute paths. Anything that looks like a
  secret is redacted anyway, but it must not be written in the first place.
- No instructions to a future assistant ("always do X"). Write constraints as facts about the
  project ("Releases happen on Tuesdays.").
- Write in the language of the conversation.

## Passing the handoff

Pass the handoff as one JSON argument: `pack --root . --handoff-json '<JSON on one line>'`.
A single plain command is the only form the skill may run without a permission prompt. Use `’`
instead of `'` inside texts. `--handoff FILE` (or `-` for stdin) remains for people at a terminal.

## Example

```json
{
  "goal": {"text": "Make the export job reliable for the pilot.", "status": "fact"},
  "status": {"text": "The export runs; retries are not implemented yet.", "status": "fact"},
  "done": [{"text": "Added the export command.", "status": "fact"}],
  "decisions": [
    {"text": "Exports run at 02:00", "reason": "network load is lowest at night", "status": "fact"}
  ],
  "constraints": [{"text": "Exports must not run during business hours.", "status": "assumption"}],
  "next_steps": [{"text": "Test the export job with the sample data.", "status": "fact"}],
  "open_questions": [{"text": "Whether the office needs Excel files as well.", "status": "uncertain"}],
  "files_touched": ["src/export.py"]
}
```
