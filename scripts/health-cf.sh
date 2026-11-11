#!/usr/bin/env bash
# IncidentIQ — Cloudflare health-check (chỉ chữa cháy, không thay thế IaC)
# Kiểm tra Worker /health/live và /health/ready.
set -euo pipefail

WORKER_URL="${1:?Usage: health-cf.sh <worker-url>}"

if ! command -v curl &> /dev/null; then
    echo "❌ curl is not installed." >&2
    exit 1
fi

echo "🔎 Checking Cloudflare Worker: $WORKER_URL"

for path in /health/live /health/ready; do
    code=$(curl -s -o /tmp/incidentiq-health-body.json -w "%{http_code}" --max-time 30 \
        "${WORKER_URL}${path}" || echo "000")
    echo "HTTP $code $path"
    cat /tmp/incidentiq-health-body.json 2>/dev/null || true
    echo
    if [[ "$code" != "200" ]]; then
        echo "❌ Health check failed for $path (HTTP $code)." >&2
        exit 1
    fi
done

echo "✅ Cloudflare Worker healthy."
