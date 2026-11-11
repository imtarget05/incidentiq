#!/usr/bin/env bash
# IncidentIQ — Azure backend health-check (chỉ chữa cháy)
# Kiểm tra Container App backend /health/live và /health/ready qua edge secret.
set -euo pipefail

BACKEND_URL="${1:?Usage: health-azure.sh <backend-url>}"
EDGE_SECRET="${AZURE_EDGE_SECRET:?AZURE_EDGE_SECRET must be set}"

if ! command -v curl &> /dev/null; then
    echo "❌ curl is not installed." >&2
    exit 1
fi

echo "🔎 Checking Azure backend: $BACKEND_URL"

for path in /health/live /health/ready; do
    code=$(curl -s -o /tmp/incidentiq-azure-health.json -w "%{http_code}" --max-time 30 \
        -H "X-Edge-Secret: $EDGE_SECRET" \
        "${BACKEND_URL}${path}" || echo "000")
    echo "HTTP $code $path"
    cat /tmp/incidentiq-azure-health.json 2>/dev/null || true
    echo
    if [[ "$code" != "200" ]]; then
        echo "❌ Azure backend health check failed for $path (HTTP $code)." >&2
        exit 1
    fi
done

echo "✅ Azure backend healthy."
