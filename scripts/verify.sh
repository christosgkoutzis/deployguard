#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-deployguard}"
RELEASE_NAME="${RELEASE_NAME:-telemetry-collector}"
LOCAL_PORT="${LOCAL_PORT:-18080}"
SERVICE_PORT="${SERVICE_PORT:-80}"
SERVICE_NAME="${RELEASE_NAME}-service"
DEPLOYMENT_NAME="${RELEASE_NAME}-deployment"

for cmd in kubectl curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

echo "INFO: Waiting for deployment rollout"
kubectl -n "${NAMESPACE}" rollout status deployment/"${DEPLOYMENT_NAME}" --timeout=120s

echo "INFO: Starting temporary port-forward"
kubectl -n "${NAMESPACE}" port-forward svc/"${SERVICE_NAME}" "${LOCAL_PORT}:${SERVICE_PORT}" >/tmp/deployguard-port-forward.log 2>&1 &
PF_PID=$!
cleanup() {
  kill "$PF_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 2

echo "INFO: Checking /health"
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null

echo "INFO: Checking /metrics"
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/metrics" | grep -q "telemetry_collector_requests_total"

echo "INFO: Verification passed"
