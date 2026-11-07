# Background jobs on PostgreSQL

## Status
Accepted.

## Context
Operating Redis only for jobs was too much work.

## Decision
- Background jobs run on a PostgreSQL-based queue instead of Redis.

## Consequences
- One database fewer to operate.
