#!/usr/bin/env bash
# IncidentIQ — Azure rollback (chỉ chữa cháy, tạm thời)
# Quay traffic Container App về revision trước.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-incidentiq-prod}"
APP_NAME="${APP_NAME:-incidentiq-api}"
PREVIOUS_REVISION="${1:?Usage: rollback-azure.sh <previous-revision-name>}"

if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI (az) is not installed." >&2
    exit 1
fi

echo "🔙 Rolling back Azure Container App [$APP_NAME] to [$PREVIOUS_REVISION]"

az containerapp ingress traffic set \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --revision-weight "${PREVIOUS_REVISION}=100" \
    --output none

echo "✅ Traffic rolled back to [$PREVIOUS_REVISION]."
