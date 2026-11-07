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
