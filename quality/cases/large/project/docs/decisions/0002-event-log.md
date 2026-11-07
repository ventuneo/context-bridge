# Record harvest events in an event log

## Status
Accepted.

## Context
Auditors want to replay what happened to a batch.

## Decision
- Harvest events are written to an append-only event log.

## Consequences
- Corrections are new events, not edits.
