#!/usr/bin/env bash
# backup_d1.sh — Export IncidentIQ D1 (production) to a dated SQL file.
#
# Usage:
#   CLOUDFLARE_API_TOKEN=... ./scripts/backup_d1.sh
#   CLOUDFLARE_API_TOKEN=... DB_NAME=incidentiq-preview ./scripts/backup_d1.sh
#
# Output:
#   backups/d1-YYYY-MM-DD.sql
#
# Optionally upload to R2 or S3 by setting BACKUP_BUCKET:
#   BACKUP_BUCKET=s3://my-bucket/incidentiq-backups ./scripts/backup_d1.sh

set -euo pipefail

DB_NAME="${DB_NAME:-ai-knowledge-platform}"
BACKUP_DIR="backups"
DATE="$(date -u +%Y-%m-%d)"
OUTFILE="${BACKUP_DIR}/d1-${DATE}.sql"

mkdir -p "$BACKUP_DIR"

echo "Backing up D1 database '${DB_NAME}' → ${OUTFILE} …"
npx wrangler d1 export "$DB_NAME" --remote --output "$OUTFILE"

SIZE="$(wc -c < "$OUTFILE")"
echo "✅  Backup complete: ${OUTFILE} (${SIZE} bytes)"

# Optional: upload to object storage.
if [[ -n "${BACKUP_BUCKET:-}" ]]; then
    if command -v aws &>/dev/null && [[ "$BACKUP_BUCKET" == s3://* ]]; then
        aws s3 cp "$OUTFILE" "${BACKUP_BUCKET}/${DATE}/d1.sql"
        echo "✅  Uploaded to ${BACKUP_BUCKET}/${DATE}/d1.sql"
    elif command -v rclone &>/dev/null; then
        rclone copy "$OUTFILE" "${BACKUP_BUCKET}/${DATE}/"
        echo "✅  Uploaded via rclone."
    else
        echo "⚠  BACKUP_BUCKET set but no compatible upload tool found (aws cli / rclone). Skipping upload."
    fi
fi
