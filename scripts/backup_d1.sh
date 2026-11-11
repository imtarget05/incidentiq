#!/usr/bin/env bash
# IncidentIQ — D1 disaster-recovery backup (Phase 3).
#
# Exports the remote D1 database to a timestamped SQL file and prunes old
# exports, keeping the last N (default 14).
#
# Usage:
#   ./scripts/backup_d1.sh [--output-dir DIR] [--keep N]
#   RETENTION_COUNT=30 ./scripts/backup_d1.sh
#
# Options:
#   --output-dir DIR   Directory for backups (default: ./backups, or $OUTPUT_DIR)
#   --keep N           Number of exports to retain (default: 14, or $RETENTION_COUNT)
#
# Scheduling:
#   Run from a GitHub Actions cron workflow (e.g. hourly) or any cron job:
#     0 * * * *  cd <repo> && ./scripts/backup_d1.sh
#   Requires `wrangler` on PATH and CLOUDFLARE_API_TOKEN (wrangler auth).
#   For restores, see scripts/restore_d1.sh.
#
# NOTE: Cloudflare D1 also has Time Travel (30-day point-in-time restore).
# This script complements it with long-lived, operator-owned snapshots.
set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-backups}"
KEEP="${RETENTION_COUNT:-14}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --output-dir=*) OUTPUT_DIR="${1#*=}"; shift ;;
    --keep) KEEP="$2"; shift 2 ;;
    --keep=*) KEEP="${1#*=}"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

# Always run from the repo root so --config wrangler.toml resolves.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

command -v wrangler >/dev/null 2>&1 || {
  echo "ERROR: wrangler is not on PATH (or set WRANGLER=wrun wrapper)" >&2
  exit 1
}

if ! [[ "$KEEP" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --keep must be a non-negative integer (got '$KEEP')" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="$OUTPUT_DIR/ai-knowledge-$STAMP.sql"

echo "Exporting D1 database 'ai-knowledge-platform' -> $OUTPUT_FILE"
wrangler d1 export ai-knowledge-platform --remote --output "$OUTPUT_FILE" --config wrangler.toml

if [[ ! -s "$OUTPUT_FILE" ]]; then
  echo "ERROR: export produced an empty file: $OUTPUT_FILE" >&2
  exit 1
fi

echo "Pruning exports older than the last $KEEP in $OUTPUT_DIR"
# shellcheck disable=SC2012  # ls -t is fine for this simple, local prune
ls -1t "$OUTPUT_DIR"/ai-knowledge-*.sql 2>/dev/null | tail -n +$((KEEP + 1)) | while IFS= read -r old; do
  echo "  removing $old"
  rm -f -- "$old"
done

echo "OK: backup written to $OUTPUT_FILE (retention: last $KEEP exports)"
