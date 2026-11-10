#!/usr/bin/env bash
# Remote deployment through this legacy local script is intentionally disabled.
# The base Wrangler configs reference non-preview resources; use the isolated
# GitHub Actions preview workflow after configuring separate preview resources.
set -euo pipefail

echo "Local remote deployment is disabled for safety." >&2
echo "Configure the preview environment and run .github/workflows/deploy-preview.yml." >&2
echo "This script has no production deployment path." >&2
exit 2
