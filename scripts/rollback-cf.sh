#!/usr/bin/env bash
# IncidentIQ — Cloudflare rollback (chỉ chữa cháy, tạm thời)
# Quay lại revision Worker trước đây bằng wrangler rollback.
set -euo pipefail

SCRIPT_NAME="${1:?Usage: rollback-cf.sh <script-name>}"
ENVIRONMENT="${2:-production}"

if ! command -v wrangler &> /dev/null; then
    echo "❌ wrangler is not installed." >&2
    exit 1
fi

echo "🔙 Rolling back Cloudflare Worker [$SCRIPT_NAME] ($ENVIRONMENT)"

wrangler rollback "$SCRIPT_NAME" --env "$ENVIRONMENT" || \
    wrangler rollback "$SCRIPT_NAME"

echo "✅ Rollback initiated for [$SCRIPT_NAME]."
