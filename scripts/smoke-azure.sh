#!/usr/bin/env bash
# IncidentIQ — Azure backend smoke test (chỉ chữa cháy)
# Gọi health và MCP tools/list trên Azure backend qua edge secret.
set -euo pipefail

BACKEND_URL="${1:?Usage: smoke-azure.sh <backend-url> <edge-secret> <api-key>}"
EDGE_SECRET="${2:?Usage: smoke-azure.sh <backend-url> <edge-secret> <api-key>}"
API_KEY="${3:?Usage: smoke-azure.sh <backend-url> <edge-secret> <api-key>}"

if ! command -v curl &> /dev/null; then
    echo "❌ curl is not installed." >&2
    exit 1
fi

echo "🔎 Running smoke test against Azure backend: $BACKEND_URL"

# Health ready.
code=$(curl -s -o /tmp/incidentiq-azure-smoke.json -w "%{http_code}" --max-time 30 \
    -H "X-Edge-Secret: $EDGE_SECRET" \
    "${BACKEND_URL}/health/ready" || echo "000")
echo "GET /health/ready -> $code"
if [[ "$code" != "200" ]]; then
    echo "❌ Azure backend /health/ready returned $code." >&2
    exit 1
fi

# MCP tools/list.
resp=$(curl -s --max-time 30 \
    -H "X-Edge-Secret: $EDGE_SECRET" \
    -H "X-Api-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    "${BACKEND_URL}/mcp" || true)
echo "MCP tools/list: $resp"
echo "$resp" | python3 -c 'import json,sys; d=json.load(sys.stdin); names={t["name"] for t in d.get("result",{}).get("tools",[])}; assert {"search_runbooks","get_incident","get_triage_report"} <= names, f"Missing tools: {names}"' || {
    echo "❌ Azure MCP tools/list missing required tools." >&2
    exit 1
}

echo "✅ Azure backend smoke test passed."
