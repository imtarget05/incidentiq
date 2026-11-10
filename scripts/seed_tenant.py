"""Seed demo tenants + API keys for IncidentIQ.

Creates two workspaces (tenant A, tenant B) to demonstrate tenant isolation.
Each tenant gets its own workspace with an investigator role.

Usage:
  python scripts/seed_tenant.py --names "Tenant A" "Tenant B"

Apply the printed SQL with:
  wrangler d1 execute ai-knowledge-platform --remote --file=./scripts/seed.sql
  # or local:
  wrangler d1 execute ai-knowledge-platform --local --file=./scripts/seed.sql

Plaintext API keys are printed ONCE. Store them securely.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api" / "src"))

from main import _sha256_hex  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Seed demo tenants + API keys")
    parser.add_argument("--names", nargs="+", default=["Tenant A", "Tenant B"],
                        help="Tenant names (default: Tenant A, Tenant B)")
    args = parser.parse_args()

    now = int(time.time() * 1000)
    statements = []
    print("=" * 60)
    print("SEEDING TENANTS (tenant isolation demo)")
    print("=" * 60)
    for name in args.names:
        tenant_id = str(uuid.uuid4())
        workspace_id = str(uuid.uuid4())
        api_key = "sk_" + secrets.token_urlsafe(24)
        prefix = api_key[:8]
        key_hash = _sha256_hex(api_key)
        member_id = str(uuid.uuid4())

        statements.append(
            f"INSERT INTO tenants (id, name, created_at, is_active) "
            f"VALUES ('{tenant_id}', '{name}', {now}, 1);"
        )
        statements.append(
            f"INSERT INTO workspaces (id, name, created_at, is_active) "
            f"VALUES ('{workspace_id}', 'Workspace for {name}', {now}, 1);"
        )
        statements.append(
            f"INSERT INTO workspace_members (id, workspace_id, tenant_id, role, created_at) "
            f"VALUES ('{member_id}', '{workspace_id}', '{tenant_id}', 'investigator', {now});"
        )
        statements.append(
            f"INSERT INTO api_keys (id, tenant_id, key_prefix, key_hash, created_at, is_active) "
            f"VALUES ('{str(uuid.uuid4())}', '{tenant_id}', '{prefix}', '{key_hash}', {now}, 1);"
        )

        print()
        print(f"TENANT : {name}")
        print(f"TENANT_ID : {tenant_id}")
        print(f"WORKSPACE_ID : {workspace_id}")
        print(f"API_KEY   : {api_key}")
        print(f"PREFIX    : {prefix}")
        print("Store API_KEY securely — it is shown only once.")

    sql = "\n".join(statements)
    print()
    print("--- seed.sql ---")
    print(sql)
    out = Path("scripts/seed.sql")
    out.write_text(sql)
    print(f"SQL written to {out}")


if __name__ == "__main__":
    main()
