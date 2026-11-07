# Background jobs on Redis

## Status
Superseded by 0010.

## Context
Jobs were slow inside web requests.

## Decision
- Background jobs run on a Redis queue.

## Consequences
- Redis has to be operated.
