#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/verify.sh
# Optional: RELEASE_NAMES=my-service EXPECTED_METRIC=http_requests_total PROM_EXPECTED_JOBS=my-service,prometheus HEALTH_PATH=/health METRICS_PATH=/metrics ./scripts/verify.sh

NAMESPACE="${NAMESPACE:-deployguard}"
RELEASE_NAMES="${RELEASE_NAMES:-}"
LOCAL_PORT="${LOCAL_PORT:-18080}"
SERVICE_PORT="${SERVICE_PORT:-80}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
METRICS_PATH="${METRICS_PATH:-/metrics}"
EXPECTED_METRIC="${EXPECTED_METRIC:-}"
VERIFY_MONITORING="${VERIFY_MONITORING:-true}"
PROM_NAMESPACE="${PROM_NAMESPACE:-monitoring}"
PROM_RELEASE_NAME="${PROM_RELEASE_NAME:-prometheus}"
PROM_EXPECTED_JOBS="${PROM_EXPECTED_JOBS:-}"
PROM_SERVICE_NAME="${PROM_SERVICE_NAME:-${PROM_RELEASE_NAME}-server}"
PROM_LOCAL_PORT="${PROM_LOCAL_PORT:-19090}"
PROM_SERVICE_PORT="${PROM_SERVICE_PORT:-80}"
PROM_PORT_FORWARD_LOG="${PROM_PORT_FORWARD_LOG:-/tmp/${PROM_RELEASE_NAME}-port-forward.log}"

for cmd in kubectl curl python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

if [[ -z "${RELEASE_NAMES// }" ]]; then
  mapfile -t DETECTED_RELEASES < <(kubectl -n argocd get applications -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | sort | grep -v '^prometheus$' || true)
  if [[ ${#DETECTED_RELEASES[@]} -eq 0 ]]; then
    echo "ERROR: RELEASE_NAMES not provided and no ArgoCD service applications were detected"
    exit 1
  fi
  RELEASE_NAMES="$(IFS=','; echo "${DETECTED_RELEASES[*]}")"
  echo "INFO: Auto-detected RELEASE_NAMES=${RELEASE_NAMES}"
fi

if [[ "${HEALTH_PATH}" != /* ]] || [[ "${METRICS_PATH}" != /* ]]; then
  echo "ERROR: HEALTH_PATH and METRICS_PATH must start with '/'"
  exit 1
fi

IFS=',' read -r -a RELEASE_LIST <<< "${RELEASE_NAMES}"

# Kill any existing port-forward processes on exit
cleanup() {
  if [[ -n "${PF_PID:-}" ]]; then
    kill "${PF_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${PROM_PF_PID:-}" ]]; then
    kill "${PROM_PF_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for release in "${RELEASE_LIST[@]}"; do
  release_name="${release// /}"

  if [[ -z "${release_name}" ]]; then
    echo "ERROR: RELEASE_NAMES contains an empty entry"
    exit 1
  fi

  service_name="${release_name}-service"
  deployment_name="${release_name}-deployment"
  port_forward_log="/tmp/${release_name}-port-forward.log"

  echo "INFO: Waiting for deployment rollout for ${deployment_name}"
  kubectl -n "${NAMESPACE}" rollout status deployment/"${deployment_name}" --timeout=120s

  echo "INFO: Starting temporary port-forward for ${service_name}"
  kubectl -n "${NAMESPACE}" port-forward svc/"${service_name}" "${LOCAL_PORT}:${SERVICE_PORT}" >"${port_forward_log}" 2>&1 &
  PF_PID=$!

# Wait for port-forward to actually start accepting connections (timeout 10s)
  wait_time=0
  while ! curl -fsS "http://127.0.0.1:${LOCAL_PORT}${HEALTH_PATH}" >/dev/null 2>&1; do
    sleep 1
    wait_time=$((wait_time + 1))
    if [[ ${wait_time} -ge 10 ]]; then echo "ERROR: Port-forward timeout for ${release_name}"; exit 1; fi
  done

  echo "INFO: Checking ${HEALTH_PATH} for ${release_name}"
  if ! curl -fsS "http://127.0.0.1:${LOCAL_PORT}${HEALTH_PATH}" >/dev/null; then
    echo "ERROR: Health endpoint ${HEALTH_PATH} failed for ${release_name}"
    exit 1
  fi

  echo "INFO: Checking ${METRICS_PATH} for ${release_name}"
  if ! METRICS_BODY=$(curl -fsS "http://127.0.0.1:${LOCAL_PORT}${METRICS_PATH}"); then
    echo "ERROR: Metrics endpoint ${METRICS_PATH} unreachable for ${release_name}"
    exit 1
  fi
  if [[ -n "${EXPECTED_METRIC}" ]]; then
    if ! echo "${METRICS_BODY}" | grep -q "${EXPECTED_METRIC}"; then
      echo "ERROR: Expected metric '${EXPECTED_METRIC}' not found for ${release_name}"
      exit 1
    fi
  else
    if ! echo "${METRICS_BODY}" | grep -Eq '# HELP|# TYPE'; then
      echo "ERROR: No Prometheus metrics format detected for ${release_name}"
      exit 1
    fi
  fi

  kill "${PF_PID}" >/dev/null 2>&1 || true
  wait "${PF_PID}" 2>/dev/null || true
  unset PF_PID
done

if [[ "${VERIFY_MONITORING}" == "true" ]]; then
  if [[ -z "${PROM_EXPECTED_JOBS// }" ]]; then
    PROM_EXPECTED_JOBS="${RELEASE_NAMES},prometheus"
  fi

  IFS=',' read -r -a PROM_JOB_LIST <<< "${PROM_EXPECTED_JOBS}"

  if kubectl -n "${PROM_NAMESPACE}" get svc "${PROM_SERVICE_NAME}" >/dev/null 2>&1; then
    echo "INFO: Starting Prometheus port-forward"
    kubectl -n "${PROM_NAMESPACE}" port-forward svc/"${PROM_SERVICE_NAME}" "${PROM_LOCAL_PORT}:${PROM_SERVICE_PORT}" >"${PROM_PORT_FORWARD_LOG}" 2>&1 &
    PROM_PF_PID=$!

    sleep 10

    echo "INFO: Checking Prometheus targets"
    if ! TARGETS_JSON=$(curl -fsS "http://127.0.0.1:${PROM_LOCAL_PORT}/api/v1/targets"); then
      echo "ERROR: Prometheus targets check failed. Port-forward logs:"
      cat "${PROM_PORT_FORWARD_LOG}"
      exit 1
    fi
    for job in "${PROM_JOB_LIST[@]}"; do
      job_name="${job// /}"
      if [[ -z "${job_name}" ]]; then
        echo "ERROR: PROM_EXPECTED_JOBS contains an empty entry"
        exit 1
      fi

      if ! python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
targets = data.get('data', {}).get('activeTargets', [])
all_jobs = {t['labels'].get('job') for t in targets}
up_jobs  = {t['labels'].get('job') for t in targets if t.get('health') == 'up'}
job = '${job_name}'
assert job in all_jobs, f\"Prometheus job '{job}' not found in targets\"
assert job in up_jobs,  f\"Prometheus job '{job}' has no healthy ('up') target\"
" <<< "${TARGETS_JSON}"; then
        echo "ERROR: Prometheus job '${job_name}' not found or not healthy"
        exit 1
      fi
    done

    if [[ -n "${EXPECTED_METRIC}" ]]; then
      echo "INFO: Checking Prometheus query"
      if ! QUERY_JSON=$(curl -fsS --get --data-urlencode "query=${EXPECTED_METRIC}" "http://127.0.0.1:${PROM_LOCAL_PORT}/api/v1/query"); then
        echo "ERROR: Prometheus query check failed. Port-forward logs:"
        cat "${PROM_PORT_FORWARD_LOG}"
        exit 1
      fi
      if ! echo "${QUERY_JSON}" | grep -q '"status":"success"'; then
        echo "ERROR: Prometheus query for '${EXPECTED_METRIC}' failed"
        exit 1
      fi
    else
      echo "INFO: EXPECTED_METRIC not set, skipping Prometheus query check"
    fi
  else
    echo "INFO: Prometheus service not found, skipping monitoring checks"
  fi
else
  echo "INFO: VERIFY_MONITORING=false, skipping monitoring checks"
fi

echo "INFO: Verification passed"
