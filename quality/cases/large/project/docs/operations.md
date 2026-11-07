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
