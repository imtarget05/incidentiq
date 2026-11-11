#!/usr/bin/env bash
# IncidentIQ — Cloudflare smoke test (chỉ chữa cháy)
# Gọi protected endpoint (401 nếu thiếu key) và MCP tools/list.
set -euo pipefail

WORKER_URL="${1:?Usage: smoke-cf.sh <worker-url> <api-key>}"
API_KEY="${2:?Usage: smoke-cf.sh <worker-url> <api-key>}"

if ! command -v curl &> /dev/null; then
    echo "❌ curl is not installed." >&2
    exit 1
fi

echo "🔎 Running smoke test against Cloudflare Worker: $WORKER_URL"

# Protected endpoint without key -> expect 401.
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 \
    "${WORKER_URL}/api/v1/workspaces" || echo "000")
echo "GET /api/v1/workspaces (no key) -> $code"
if [[ "$code" != "401" ]]; then
    echo "❌ Expected 401 for unauthenticated request, got $code." >&2
    exit 1
fi

# MCP tools/list with key.
resp=$(curl -s --max-time 30 \
    -H "X-Api-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    "${WORKER_URL}/mcp" || true)
echo "MCP tools/list: $resp"
echo "$resp" | python3 -c 'import json,sys; d=json.load(sys.stdin); names={t["name"] for t in d.get("result",{}).get("tools",[])}; assert {"search_runbooks","get_incident","get_triage_report"} <= names, f"Missing tools: {names}"' || {
    echo "❌ MCP tools/list missing required tools." >&2
    exit 1
}

echo "✅ Cloudflare smoke test passed."
