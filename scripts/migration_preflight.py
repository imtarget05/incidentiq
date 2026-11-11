#!/usr/bin/env python3
"""Read-only duplicate-key preflight before migration 004.

Local: python scripts/migration_preflight.py --database /path/to/database.sqlite
Remote: --sql prints SELECTs for an operator to run using wrangler d1 execute.
Never changes keys, merges records or applies a migration.
"""
import argparse
import json
from pathlib import Path
import sqlite3

QUERIES = {
    table: f"SELECT tenant_id, idempotency_key, COUNT(*) AS record_count, GROUP_CONCAT(id) AS record_ids FROM {table} WHERE idempotency_key IS NOT NULL GROUP BY tenant_id, idempotency_key HAVING COUNT(*) > 1"
    for table in ("documents", "incidents")
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=Path, help="existing SQLite file opened read-only")
    source.add_argument("--sql", action="store_true", help="print read-only D1 queries; no remote access")
    args = parser.parse_args()
    if args.sql:
        for table, query in QUERIES.items():
            print(f"-- {table}\n{query};")
        return 0
    try:
        with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            duplicates = {table: [dict(row) for row in db.execute(query)] for table, query in QUERIES.items()}
    except sqlite3.Error as exc:
        print(json.dumps({"ready": False, "error": str(exc)}))
        return 2
    ready = not any(duplicates.values())
    print(json.dumps({"ready": ready, "duplicates": duplicates,
                      "action": "Apply migration only after reviewing this report." if ready else "Resolve ambiguous keys with resource owners; no records were changed."}, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
