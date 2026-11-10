#!/usr/bin/env bash
# IncidentIQ — post-deploy smoke test.
#
# Usage:
#   ./scripts/smoke_test.sh https://<worker>.workers.dev [API_KEY]
#
# Exits non-zero if any check fails. Never mutates Production infrastructure;
# it only creates a sandbox incident record in the deployed D1 database.
set -uo pipefail

BASE_URL="${1:-${API_WORKER_URL:-}}"
API_KEY="${2:-${API_KEY:-}}"
BASE_URL="${BASE_URL%/}"

if [[ -z "$BASE_URL" ]]; then
  echo "usage: $0 <base-url> [api-key]" >&2
  exit 2
fi

command -v curl >/dev/null || { echo "curl is required" >&2; exit 2; }

pass=0
fail=0
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

req() {
  local method="$1" path="$2" expect="$3" label="$4"
  shift 4
  local code
  code="$(curl -sS --max-time 30 -o "$tmp" -w '%{http_code}' -X "$method" "$BASE_URL$path" "$@" || echo 000)"
  if [[ "$code" == "$expect" ]]; then
    echo "  PASS  $label ($method $path -> $code)"
    pass=$((pass + 1))
  else
    echo "  FAIL  $label ($method $path -> $code, expected $expect)"
    sed 's/^/        /' "$tmp" | head -5
    fail=$((fail + 1))
  fi
}

echo "Smoke testing $BASE_URL"

req GET /health 200 "health endpoint"
if python3 - "$tmp" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body.get("status") in ("ok", "degraded"), body
PY
then
  echo "  PASS  health payload reports ok/degraded"
  pass=$((pass + 1))
else
  echo "  FAIL  health payload is not JSON with status ok|degraded"
  fail=$((fail + 1))
fi

if [[ -n "$API_KEY" ]]; then
  idem="smoke-$(date +%s)-$$"
  req POST /api/v1/incidents 201 "create incident" \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: $API_KEY" \
    -H "Idempotency-Key: $idem" \
    -d '{"title":"smoke test incident","severity":"LOW","service":"smoke","environment":"staging"}'

  incident_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("incident_id",""))' "$tmp" 2>/dev/null || true)"
  if [[ -n "$incident_id" ]]; then
    req GET "/api/v1/incidents/$incident_id" 200 "get incident" -H "X-Api-Key: $API_KEY"

    req POST "/api/v1/incidents/$incident_id/events" 201 "append event" \
      -H "Content-Type: application/json" \
      -H "X-Api-Key: $API_KEY" \
      -d '{"event_type":"event_added","message":"smoke test event"}'

    req POST "/api/v1/incidents/$incident_id/triage" 200 "grounded triage" \
      -H "Content-Type: application/json" \
      -H "X-Api-Key: $API_KEY" \
      -H "Idempotency-Key: triage-$idem" \
      -d '{}'
  else
    echo "  FAIL  could not read incident id from create response"
    fail=$((fail + 1))
  fi

  req GET /api/v1/metrics/quota 200 "quota dashboard" -H "X-Api-Key: $API_KEY"
else
  echo "  SKIP  authenticated checks (no API_KEY given)"
  echo "        provide an API key belonging to a tenant in the target preview database"
fi

echo
echo "Result: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
