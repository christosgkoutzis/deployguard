#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/verify.sh
# Optional: EXPECTED_METRIC=telemetry_collector_requests_total ./scripts/verify.sh

NAMESPACE="${NAMESPACE:-deployguard}"
RELEASE_NAME="${RELEASE_NAME:-telemetry-collector}"
LOCAL_PORT="${LOCAL_PORT:-18080}"
SERVICE_PORT="${SERVICE_PORT:-80}"
EXPECTED_METRIC="${EXPECTED_METRIC:-telemetry_collector_requests_total}"
SERVICE_NAME="${RELEASE_NAME}-service"
DEPLOYMENT_NAME="${RELEASE_NAME}-deployment"
PORT_FORWARD_LOG="${PORT_FORWARD_LOG:-/tmp/${RELEASE_NAME}-port-forward.log}"
VERIFY_MONITORING="${VERIFY_MONITORING:-true}"
PROM_NAMESPACE="${PROM_NAMESPACE:-monitoring}"
PROM_RELEASE_NAME="${PROM_RELEASE_NAME:-prometheus}"
PROM_SERVICE_NAME="${PROM_SERVICE_NAME:-${PROM_RELEASE_NAME}-server}"
PROM_LOCAL_PORT="${PROM_LOCAL_PORT:-19090}"
PROM_SERVICE_PORT="${PROM_SERVICE_PORT:-80}"
PROM_PORT_FORWARD_LOG="${PROM_PORT_FORWARD_LOG:-/tmp/${PROM_RELEASE_NAME}-port-forward.log}"

for cmd in kubectl curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

echo "INFO: Waiting for deployment rollout"
kubectl -n "${NAMESPACE}" rollout status deployment/"${DEPLOYMENT_NAME}" --timeout=120s

echo "INFO: Starting temporary port-forward"
kubectl -n "${NAMESPACE}" port-forward svc/"${SERVICE_NAME}" "${LOCAL_PORT}:${SERVICE_PORT}" >"${PORT_FORWARD_LOG}" 2>&1 &
PF_PID=$!
cleanup() {
  kill "$PF_PID" >/dev/null 2>&1 || true
  if [[ -n "${PROM_PF_PID:-}" ]]; then
    kill "${PROM_PF_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

sleep 2

echo "INFO: Checking /health"
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null

echo "INFO: Checking /metrics"
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/metrics" | grep -q "${EXPECTED_METRIC}"

if [[ "${VERIFY_MONITORING}" == "true" ]]; then
  if kubectl -n "${PROM_NAMESPACE}" get svc "${PROM_SERVICE_NAME}" >/dev/null 2>&1; then
    echo "INFO: Starting Prometheus port-forward"
    kubectl -n "${PROM_NAMESPACE}" port-forward svc/"${PROM_SERVICE_NAME}" "${PROM_LOCAL_PORT}:${PROM_SERVICE_PORT}" >"${PROM_PORT_FORWARD_LOG}" 2>&1 &
    PROM_PF_PID=$!

    sleep 2

    echo "INFO: Checking Prometheus targets"
    TARGETS_JSON=$(curl -fsS "http://127.0.0.1:${PROM_LOCAL_PORT}/api/v1/targets")
    echo "${TARGETS_JSON}" | grep -q '"job":"telemetry-collector"'
    echo "${TARGETS_JSON}" | grep -q '"health":"up"'

    echo "INFO: Checking Prometheus query"
    QUERY_JSON=$(curl -fsS --get --data-urlencode "query=${EXPECTED_METRIC}" "http://127.0.0.1:${PROM_LOCAL_PORT}/api/v1/query")
    echo "${QUERY_JSON}" | grep -q '"status":"success"'
  else
    echo "INFO: Prometheus service not found, skipping monitoring checks"
  fi
else
  echo "INFO: VERIFY_MONITORING=false, skipping monitoring checks"
fi

echo "INFO: Verification passed"
