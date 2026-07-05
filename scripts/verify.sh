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
PLATFORM_APPS="${PLATFORM_APPS:-prometheus}"
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
  IFS=',' read -r -a PLATFORM_APPS_LIST <<< "${PLATFORM_APPS}"
  mapfile -t ALL_DETECTED < <(kubectl -n argocd get applications -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | sort || true)
 
  declare -a FILTERED_RELEASES=()
  for app in "${ALL_DETECTED[@]}"; do
    is_platform=false
    for p in "${PLATFORM_APPS_LIST[@]}"; do
      [[ "${app}" == "${p// /}" ]] && is_platform=true && break
    done
    [[ "${is_platform}" == "false" ]] && FILTERED_RELEASES+=("${app}")
  done

  if [[ ${#FILTERED_RELEASES[@]} -eq 0 ]]; then
    echo "ERROR: RELEASE_NAMES not provided and no ArgoCD service applications were detected"
    exit 1
  fi
  RELEASE_NAMES="$(IFS=','; echo "${FILTERED_RELEASES[*]}")"
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
  port_forward_log="/tmp/${release_name}-port-forward.log"

  echo "INFO: Checking PVCs for ${release_name} (if applicable)"
  pvc_list=$(kubectl -n "${NAMESPACE}" get pvc -l "app=${release_name}" -o jsonpath="{.items[*].metadata.name}" 2>/dev/null || true)
  for pvc in ${pvc_list}; do
    phase=$(kubectl -n "${NAMESPACE}" get pvc "${pvc}" -o jsonpath='{.status.phase}')
    if [[ "${phase}" != "Bound" ]]; then
      echo "ERROR: PVC '${pvc}' is in state '${phase}', expected 'Bound'"
      exit 1
    fi
    echo "INFO: PVC '${pvc}' successfully Bound"
  done

  echo "INFO: Waiting for workload rollout for ${release_name}"
  workload_type=$(kubectl -n "${NAMESPACE}" get deploy,sts -l "app=${release_name}" -o jsonpath='{.items[0].kind}' 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)
  workload_name=$(kubectl -n "${NAMESPACE}" get deploy,sts -l "app=${release_name}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  
  if [[ -z "${workload_name}" ]]; then
    echo "ERROR: Could not detect Deployment or StatefulSet for ${release_name}"
    exit 1
  fi
  kubectl -n "${NAMESPACE}" rollout status "${workload_type}/${workload_name}" --timeout=120s

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

    echo "INFO: Waiting for Prometheus targets to become healthy..."
    max_retries=15
    retry_count=0
    targets_healthy=false

    while [[ ${retry_count} -lt ${max_retries} ]]; do
      if TARGETS_JSON=$(curl -fsS "http://127.0.0.1:${PROM_LOCAL_PORT}/api/v1/targets" 2>/dev/null); then
        all_up=true
        for job in "${PROM_JOB_LIST[@]}"; do
          job_name="${job// /}"
          if [[ -z "${job_name}" ]]; then continue; fi
          if ! python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
targets = data.get('data', {}).get('activeTargets', [])
up_jobs  = {t['labels'].get('job') for t in targets if t.get('health') == 'up'}
if '${job_name}' not in up_jobs: sys.exit(1)
" <<< "${TARGETS_JSON}" >/dev/null 2>&1; then
            all_up=false
            break
          fi
        done
        if [[ "${all_up}" == "true" ]]; then
          targets_healthy=true
          break
        fi
      fi
      sleep 5
      retry_count=$((retry_count + 1))
    done

    if [[ "${targets_healthy}" == "false" ]]; then
      echo "ERROR: Prometheus targets did not become healthy in time."
      exit 1
    fi

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
