# Orchard Logistics

Orchard Logistics plans harvest, cooling and delivery for a cooperative of fruit farms.

## Goals
- Every harvest batch is traceable from the tree row to the delivery note.
- Cold storage capacity is planned at least two weeks ahead.
- Drivers get their delivery routes before six in the morning.
- The cooperative office sees the daily yield forecast on one screen.

## Getting started
```sh
make install
make dev
make test
```

## Status
Status: the planning service runs in production for three farms.

## Architecture
- services/planner plans harvest and cooling slots.
- services/routes builds the delivery routes.
- web/office is the dashboard for the cooperative office.

# Agent rules

## Security rules
- Never print secrets or tokens in logs.
- Personal data of pickers stays in the cooperative's own data centre.
- Do not run database migrations against production without a backup.

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

# Operations

## Runbook
When the planner stops answering, check the database connections first, then the job queue. Restart the
planner only after the queue is empty, because half-finished slot bookings are retried from the queue.
The route service can keep running while the planner restarts; it uses the last published plan.

During the harvest season the on-call person checks the cooling dashboard every morning and compares the
booked slots with the real arrivals of the previous day.

## Constraints
- Backups are encrypted and kept for ninety days.
- The office dashboard must load in under two seconds.

## Development
- Archive key: {{FAKE_AWS_KEY}}

## Commands
```sh
make backup
make restore
```

# Assumptions

## Assumptions
- Assumption: every farm has a stable mobile network at the cooling house.
- Assumption: the cooperative keeps the same accounting system for two years.
- Assumption: drivers use company phones.

# Glossary

## Terms
- Batch: all crates of one variety picked in one tree row on one day.
- Slot: a four-hour window in a cooling house.
- Delivery note: the paper or PDF that goes with every truck.
- Void record: a harvest record that was cancelled but kept for the audit trail.
- Cooling house: a building with cold rooms shared by several farms.
