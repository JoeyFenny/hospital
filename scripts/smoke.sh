#!/usr/bin/env bash
set -euo pipefail

# Simple smoke test for the API endpoints.
# Usage:
#   BASE_URL=http://localhost:8000 DRG=470 ZIP=10001 RADIUS=40 ./scripts/smoke.sh

BASE_URL=${BASE_URL:-http://localhost:8000}
DRG=${DRG:-470}
ZIP=${ZIP:-10001}
RADIUS=${RADIUS:-40}

echo "==> GET /"
curl -fsS "${BASE_URL}/" | jq . >/dev/null 2>&1 || curl -fsS "${BASE_URL}/" >/dev/null

echo "==> GET /providers?drg=${DRG}&zip=${ZIP}&radius_km=${RADIUS}"
curl -fsS "${BASE_URL}/providers?drg=${DRG}&zip=${ZIP}&radius_km=${RADIUS}" | jq '.[0]' >/dev/null 2>&1 || \
  curl -fsS "${BASE_URL}/providers?drg=${DRG}&zip=${ZIP}&radius_km=${RADIUS}" >/dev/null

echo "==> POST /ask"
curl -fsS -X POST "${BASE_URL}/ask" \
  -H 'Content-Type: application/json' \
  -d "{\"question\":\"Who is cheapest for DRG ${DRG} within ${RADIUS} km of ${ZIP}?\"}" \
  | jq . >/dev/null 2>&1 || true

echo "OK"


