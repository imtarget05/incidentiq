#!/usr/bin/env bash
# IncidentIQ — D1 backup (chỉ chữa cháy)
# Export D1 database ra file SQL (Cloudflare D1 time-travel 30 ngày).
set -euo pipefail

D1_DATABASE="${1:?Usage: backup-d1.sh <d1-database-name>}"
OUTPUT_FILE="${2:-./backups/d1-$(date +%Y%m%d%H%M%S).sql}"

if ! command -v wrangler &> /dev/null; then
    echo "❌ wrangler is not installed." >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"

echo "📦 Backing up D1 database [$D1_DATABASE] to $OUTPUT_FILE"

wrangler d1 export "$D1_DATABASE" --remote --output "$OUTPUT_FILE"

echo "✅ D1 backup written to $OUTPUT_FILE"
