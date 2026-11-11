#!/usr/bin/env bash
# IncidentIQ — Azure PostgreSQL backup (chỉ chữa cháy)
# pg_dump cơ sở dữ liệu IncidentIQ trên Azure PostgreSQL Flexible Server.
set -euo pipefail

PG_HOST="${PG_HOST:?PG_HOST must be set}"
PG_DB="${PG_DB:-incidentiq}"
PG_USER="${PG_USER:?PG_USER must be set}"
PG_PASSWORD="${PG_PASSWORD:?PG_PASSWORD must be set}"
OUTPUT_FILE="${OUTPUT_FILE:-./backups/pg-$(date +%Y%m%d%H%M%S).sql}"

if ! command -v pg_dump &> /dev/null; then
    echo "❌ pg_dump is not installed." >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"

echo "📦 Backing up Azure PostgreSQL database [$PG_DB] to $OUTPUT_FILE"

export PGPASSWORD="$PG_PASSWORD"
pg_dump -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -f "$OUTPUT_FILE"

echo "✅ PostgreSQL backup written to $OUTPUT_FILE"
