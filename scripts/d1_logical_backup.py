#!/usr/bin/env python3
"""D1 logical backup: table-by-table dump that works around the D1 export
limitation ("cannot export databases with virtual tables (like FTS5)").

For every non-internal, non-FTS table this writes the row count and the rows
as a JSON document; a companion .sql file with INSERT statements is generated
for restore drills. FTS tables are skipped on purpose: they are derived from
chunks/incidents and are rebuilt with INSERT INTO <fts> SELECT after restore.

Usage:
  python scripts/d1_logical_backup.py incidentiq-preview --remote
  python scripts/d1_logical_backup.py ai-knowledge-platform --remote

Output: backups/<db>-<date>.json + backups/<db>-<date>.restore.sql
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SKIP_PREFIXES = ("sqlite_", "_cf_", "d1_migrations")


def d1_json(db: str, sql: str, remote: bool) -> list[dict]:
    cmd = ["wrangler", "d1", "execute", db, "--json", "--command", sql]
    if remote:
        cmd.append("--remote")
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    # wrangler prints logs before the JSON document on stdout
    start = out.find("[")
    data = json.loads(out[start:])
    return data[0]["results"]


def sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def topo_order(db: str, names: list[str], remote: bool) -> list[str]:
    """Order tables so referenced (parent) tables come before their children."""
    deps: dict[str, set[str]] = {}
    for name in names:
        fks = d1_json(db, f'PRAGMA foreign_key_list("{name}")', remote)
        deps[name] = {fk["table"] for fk in fks if fk["table"] in names}
    order, seen = [], set()

    def visit(n: str) -> None:
        if n in seen:
            return
        seen.add(n)
        for parent in sorted(deps.get(n, ())):
            visit(parent)
        order.append(n)

    for n in names:
        visit(n)
    return order


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("database")
    ap.add_argument("--remote", action="store_true")
    ap.add_argument("--outdir", default="backups")
    args = ap.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    base = Path(args.outdir) / f"{args.database}-{date}"
    dump: dict[str, list] = {}
    # No BEGIN/COMMIT: D1 remote execute rejects explicit transactions.
    sql_lines: list[str] = []

    tables = d1_json(
        args.database,
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' "
        "AND name NOT LIKE 'sqlite_stat%' ORDER BY name",
        args.remote,
    )
    names = [t["name"] for t in tables if not t["name"].startswith(SKIP_PREFIXES)]
    names = topo_order(args.database, names, args.remote)
    print(f"{args.database}: backing up {len(names)} tables -> {base}.json")

    for name in names:
        cols = [c["name"] for c in d1_json(args.database, f'PRAGMA table_info("{name}")', args.remote)]
        rows = d1_json(args.database, f'SELECT * FROM "{name}"', args.remote)
        dump[name] = rows
        col_list = ", ".join(f'"{c}"' for c in cols)
        for row in rows:
            vals = ", ".join(sql_literal(row.get(c)) for c in cols)
            sql_lines.append(f'INSERT INTO "{name}" ({col_list}) VALUES ({vals});')
        print(f"  {name}: {len(rows)} rows")
        if len(rows) > 20000:
            print(f"  WARNING: {name} has >20k rows; verify file size after run", file=sys.stderr)

    sql_lines.append("-- restore done")
    base.with_suffix(".json").write_text(json.dumps(dump, default=str))
    base.with_suffix(".restore.sql").write_text("\n".join(sql_lines) + "\n")
    print(f"✅ wrote {base}.json and {base}.restore.sql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
