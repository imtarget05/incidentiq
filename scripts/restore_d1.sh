#!/usr/bin/env bash
# IncidentIQ — D1 disaster-recovery restore (Phase 3).
#
# ============================================================================
#  WARNING: THIS REPLACES THE CURRENT DATABASE CONTENTS.
#  Executing a backup file runs INSERT statements against the REMOTE D1
#  database. Depending on the export, rows may collide with live data or
#  duplicate records. Prefer Cloudflare D1 Time Travel for recent accidents
#  (30-day point-in-time restore); use this script for older snapshots.
# ============================================================================
#
# Usage:
#   ./scripts/restore_d1.sh backups/ai-knowledge-20260101-000000.sql
#   FORCE=1 ./scripts/restore_d1.sh backups/ai-knowledge-20260101-000000.sql  # skip prompt
#
# Pre-flight: the backup file must exist and be non-empty.
set -euo pipefail

BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "usage: $0 <backup-file>   (e.g. backups/ai-knowledge-YYYYmmdd-HHMMSS.sql)" >&2
  exit 2
fi

# Always run from the repo root so --config wrangler.toml resolves.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi
if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file is empty: $BACKUP_FILE" >&2
  exit 1
fi

command -v wrangler >/dev/null 2>&1 || {
  echo "ERROR: wrangler is not on PATH" >&2
  exit 1
}

echo
echo "======================================================================"
echo "  WARNING: RESTORE REPLACES CURRENT DATA IN 'ai-knowledge-platform'."
echo "  This executes the full contents of:"
echo "      $BACKUP_FILE"
echo "  against the REMOTE D1 database. Live rows may be overwritten."
echo "======================================================================"
echo

if [[ "${FORCE:-0}" != "1" ]]; then
  read -r -p "Type the database name (ai-knowledge-platform) to confirm: " CONFIRM
  if [[ "$CONFIRM" != "ai-knowledge-platform" ]]; then
    echo "Aborted: confirmation did not match." >&2
    exit 1
  fi
else
  echo "FORCE=1 set — skipping confirmation prompt."
fi

echo "Restoring from $BACKUP_FILE ..."
wrangler d1 execute ai-knowledge-platform --remote --file "$BACKUP_FILE" --config wrangler.toml -y

echo "OK: restore executed. Verify with:"
echo "  wrangler d1 execute ai-knowledge-platform --remote --command 'SELECT count(*) FROM documents' --config wrangler.toml -y"
