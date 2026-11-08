# Harbor Ledger

Harbor Ledger records cargo inspections at small harbours and works offline.

## Goals
- Inspectors can record a full inspection without network access.
- Reports are exported as PDF for the harbour office.

## Getting started
```sh
make install
make test
```

## Status
Status: pilot with two harbours since October.

# Harbor Ledger rules

## Rules
- Never send inspection data to external services without written approval.
- Python 3.11 and the standard library only.
- Store timestamps in UTC.

## Conventions
- Keep modules below 400 lines.
- Use English for code and comments.

# Setup

## Development
Token for the test registry: {{FAKE_GITHUB_TOKEN}}
Contact: {{FAKE_EMAIL}}

## Troubleshooting
If the build fails, clear the cache.

# Roadmap

## Next steps
- Implement the sync queue for unreliable networks.
- Add signature capture to the inspection form.

## Open questions
- Do harbour offices need Excel exports as well?

## Milestones
| Milestone | Scope |
|---|---|
| M1 | Offline capture |
| M2 | Sync |

# Changelog

## 0.3.0
- Added PDF export
- Fixed sync retry

## 0.2.0
- Old entry
