# Idempotency and migration safety

Apply migrations before deploying the updated API. Migration 004 deliberately
fails on historical duplicate document/incident keys; it does not delete or
merge records. Run this read-only check on a local database export first:

```sh
python scripts/migration_preflight.py --database /path/to/export.sqlite
```

Exit 0 means no duplicate keys, 1 reports duplicate tenant/key pairs and record
IDs to resolve with their owners, and 2 means the database could not be checked.
`--sql` prints the two read-only SELECTs for an operator to run against D1.
Neither mode creates cloud resources, applies migrations or changes records.

Uploads and incident creation enforce uniqueness per tenant and operation using
separate unique indexes. Concurrent retries return the winning resource ID;
reusing the same key for a different payload returns 409. Upload hashes preserve
the original filename/content even after a later edit. Historical rows without
a hash compare their current source fields, because the original cannot be
reconstructed. Legacy incident hashes are accepted only within the resource's
stored workspace, never across workspaces.

Question requests use migration 005's durable `(tenant, operation, key)` ledger.
The request atomically claims a 30-second lease and has a 25-second execution
budget. A concurrent request gets 409 `idempotency_in_progress` with Retry-After;
a changed question gets 409 `idempotency_conflict`. A successful replay returns
the original JSON and status 200 with `Idempotency-Replayed: true` (the older API
returned an empty duplicate notification with 202). Clients should use the
response body directly and retry 409 in-progress using the same key.

Model failure/timeouts return 503 and release the claim for retry. A process
crash leaves the claim reclaimable after lease expiration. Completion is fenced
by owner token and live lease, preventing an expired process from overwriting a
new owner's result; it gets 409 `idempotency_lease_lost`. This does not promise
exactly-once inference or billing if a provider finishes just before the worker
crashes. Completed ledger entries remain until tenant deletion; establish an
explicit replay-retention contract before adding a cleanup job.

These behaviors are verified locally with real SQLite SQL/constraints and
concurrent coroutine tests. Live D1 execution and process-kill recovery remain
separate deployment acceptance checks.
