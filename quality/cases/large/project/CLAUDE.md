# Working rules

## Rules
- Personal data of pickers stays in the cooperative's own data centre.
- Every schema change needs a reversible migration.
- Never delete harvest records; mark them as void instead.
- Times are stored in UTC and shown in the farm's local time.
- The route service must work without the planner being available.
- Payment data is only handled by the accounting system, never by this repository.
- Public endpoints require an API token and rate limits.
- Releases happen on Tuesdays only.

## Conventions
- Use type hints in all Python modules.
- Prefer small pure functions in the planner.
- Write commit messages in English.

## Commands
```sh
make lint
make test-integration
```
