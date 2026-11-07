# Use PostgreSQL for planning data

## Status
Accepted.

## Context
The planner needs transactions and reporting across farms.

## Decision
- PostgreSQL stores all planning data.

## Consequences
- Backups run every night.
