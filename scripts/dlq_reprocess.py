#!/usr/bin/env python3
"""IncidentIQ — DLQ reprocess operator script (Phase 3).

Re-enqueues ETL for documents that ended in D1 with status='failed' (they were
already dead-lettered to `etl-dlq` by the consumer, and the breaker DLQ'd
messages with reason "circuit_open").

OPERATOR PATH (verified against wrangler 4.125.0 and the repo-bundled wrangler
4.160.0): `wrangler queues` exposes list/create/update/delete/info/consumer/
pause-delivery/resume-delivery/purge/subscription — there is NO message
send/publish subcommand for Queues in the CLI, so true re-enqueue from the
shell is not possible today. Cloudflare's Queues REST API
(PUT /accounts/{account_id}/queues/{queue_id}/messages) can push messages, but
that requires account/queue ids outside this repo.

Therefore this script implements the supported two-step reset path:

  Step 1 (this script): reset documents back to status='uploaded', error=NULL.
  Step 2 (per document): trigger re-enqueue through the API worker:
      POST /api/v1/documents/{id}/reindex   (X-Api-Key auth required)
  The reindex endpoint re-runs the ETL pipeline (vector cleanup + process) and,
  in ETL_MODE=queue, re-produces a message on `etl-queue`.

Modes:
  default (dry-run): fetch failed documents and PRINT exactly what would be
                     reset and the reindex commands to run — nothing changes.
  --apply:           execute the status reset in D1. Reindex calls are still
                     printed for the operator (or scripted with curl) since
                     authentication belongs to the operator, not this script.

Usage:
  python3 scripts/dlq_reprocess.py                  # dry-run, all tenants
  python3 scripts/dlq_reprocess.py --tenant t1      # filter by tenant
  python3 scripts/dlq_reprocess.py --limit 20       # cap the batch
  python3 scripts/dlq_reprocess.py --apply          # actually reset rows
  WRANGLER=/path/to/wrangler python3 scripts/dlq_reprocess.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

DATABASE = "ai-knowledge-platform"

SELECT_FAILED = (
    "SELECT id, tenant_id, version, error FROM documents WHERE status='failed'"
)


def _sql_quote(value: str) -> str:
    """Escape a single value for inline SQL (no bind params via --command)."""
    return "'" + value.replace("'", "''") + "'"


def _find_wrangler(override: str | None) -> str:
    if override:
        return override
    wrangler = shutil.which("wrangler")
    if not wrangler:
        sys.exit("ERROR: wrangler not found on PATH (set WRANGLER=... to override)")
    return wrangler


def _d1_json(wrangler: str, sql: str) -> list[dict]:
    """Run a SELECT against remote D1 and return rows as dicts."""
    proc = subprocess.run(
        [wrangler, "d1", "execute", DATABASE, "--remote", "--json", "-y",
         "--command", sql, "--config", "wrangler.toml"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.exit(f"ERROR: wrangler d1 execute failed:\n{proc.stderr or proc.stdout}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"ERROR: could not parse wrangler output as JSON:\n{proc.stdout[:2000]}")
    # wrangler emits a list of result objects, one per statement.
    if isinstance(payload, list):
        for entry in payload:
            results = entry.get("results") if isinstance(entry, dict) else None
            if results:
                return results
        return []
    return payload.get("results", []) if isinstance(payload, dict) else []


def _queue_payloads(rows: list[dict]) -> list[dict]:
    """The queue messages a reindex trigger would (re)produce for each doc."""
    return [
        {
            "job": "etl.process",
            "document_id": r["id"],
            "tenant_id": r["tenant_id"],
            "version": r.get("version", 1),
            "reindex": True,
            "attempt": 0,
        }
        for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reprocess failed ETL documents (DLQ path).")
    parser.add_argument("--tenant", help="only reprocess documents for this tenant_id")
    parser.add_argument("--limit", type=int, default=100,
                        help="max documents to process (default 100)")
    parser.add_argument("--apply", action="store_true",
                        help="execute the status reset (default is dry-run)")
    parser.add_argument("--wrangler", default=os.environ.get("WRANGLER"),
                        help="path to the wrangler binary (default: PATH)")
    args = parser.parse_args()

    if args.limit < 1:
        sys.exit("ERROR: --limit must be >= 1")

    wrangler = _find_wrangler(args.wrangler)

    sql = f"{SELECT_FAILED} LIMIT {int(args.limit)}"
    if args.tenant:
        sql = (
            "SELECT id, tenant_id, version, error FROM documents "
            f"WHERE status='failed' AND tenant_id={_sql_quote(args.tenant)} "
            f"LIMIT {int(args.limit)}"
        )
    rows = _d1_json(wrangler, sql)

    if not rows:
        print("No documents with status='failed'. Nothing to do.")
        return 0

    payloads = _queue_payloads(rows)

    print(f"Found {len(rows)} failed document(s):")
    for r in rows:
        print(f"  - {r['id']}  tenant={r['tenant_id']}  version={r.get('version')}  error={str(r.get('error'))[:120]}")

    print("\nQueue message payloads that reindex would (re)produce")
    print("(wrangler queues has no message-send subcommand — see header; "
          "if you have Queues REST API access these are pushable directly):")
    for p in payloads:
        print(f"  {json.dumps(p)}")

    if not args.apply:
        print("\nDRY-RUN: nothing changed. Operator path after review:")
        print("  1. Re-run with --apply to reset status='uploaded', error=NULL.")
        print("  2. Re-enqueue per document via the API worker:")
        for r in rows:
            print(f"       curl -X POST $API_WORKER_URL/api/v1/documents/{r['id']}/reindex "
                  f"-H 'X-Api-Key: <{r['tenant_id']} key>'")
        return 0

    print("\nApplying reset (status='uploaded', error=NULL) ...")
    ids = [_sql_quote(r["id"]) for r in rows]
    reset_sql = (
        "UPDATE documents SET status='uploaded', error=NULL "
        f"WHERE id IN ({','.join(ids)})"
    )
    _ = _d1_json(wrangler, reset_sql)  # UPDATE returns empty results
    print(f"Reset {len(ids)} document(s) to status='uploaded'.")
    print("Next: trigger reindex per document (curl commands above) so the "
          "documents are re-enqueued to etl-queue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
