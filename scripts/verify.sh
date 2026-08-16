#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/verify.sh

NAMESPACE="${NAMESPACE:-deployguard}"
RELEASE_NAMES="${RELEASE_NAMES:-}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
EXTERNAL_DEPS="${EXTERNAL_DEPS:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for cmd in kubectl curl yq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

if [[ -z "${RELEASE_NAMES// }" ]]; then
  IFS=',' read -r -a EXTERNAL_DEPS_LIST <<< "${EXTERNAL_DEPS}"
  mapfile -t ALL_DETECTED < <(kubectl -n argocd get applications -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | sort || true)
  
  declare -a FILTERED_RELEASES=()
  for app in "${ALL_DETECTED[@]}"; do
    is_ext=false
    for p in "${EXTERNAL_DEPS_LIST[@]}"; do
      [[ "${app}" == "${p// /}" ]] && is_ext=true && break
    done
    [[ "${is_ext}" == "false" ]] && FILTERED_RELEASES+=("${app}")
  done

  if [[ ${#FILTERED_RELEASES[@]} -eq 0 ]]; then
    echo "ERROR: RELEASE_NAMES not provided and no ArgoCD service applications were detected"
    exit 1
  fi
  RELEASE_NAMES="$(IFS=','; echo "${FILTERED_RELEASES[*]}")"
  echo "INFO: Auto-detected RELEASE_NAMES=${RELEASE_NAMES}"
fi

IFS=',' read -r -a RELEASE_LIST <<< "${RELEASE_NAMES}"
for release in "${RELEASE_LIST[@]}"; do
  release_name="${release// /}"
  if [[ -z "${release_name}" ]]; then
    echo "ERROR: RELEASE_NAMES contains an empty entry"
    exit 1
  fi

  is_mock="false"
  if [[ -n "${MOCK_APP_NAMES:-}" ]]; then
    IFS=',' read -r -a mock_array <<< "${MOCK_APP_NAMES}"
    for m in "${mock_array[@]}"; do
      if [[ "${m// /}" == "${release_name}" ]]; then
        is_mock="true"
        break
      fi
    done
  fi
  
  TOPOLOGY_FILE="${TOPOLOGY_FILE:-${REPO_ROOT}/deployguard.yaml}"
  WORKLOAD_TYPE=$(yq ".services[] | select(.name == \"${release_name}\") | .type // \"webservice\"" "$TOPOLOGY_FILE" 2>/dev/null | sed 's/"//g')
  if [[ "${WORKLOAD_TYPE}" == "test" ]]; then
    echo "INFO: Archetype is 'test'. Skipping HTTP and Rollout checks for ${release_name}."
    continue
  fi
  local_health_path=$(yq ".services[] | select(.name == \"${release_name}\") | .health_endpoint // \"${HEALTH_PATH}\"" "$TOPOLOGY_FILE" 2>/dev/null | sed 's/"//g')
  [[ -z "$local_health_path" || "$local_health_path" == "null" ]] && local_health_path="${HEALTH_PATH}"

  if [[ "${is_mock}" == "true" ]]; then
    local_health_path="/__admin/"
  elif [[ "${local_health_path}" != /* ]]; then
    echo "ERROR: health_endpoint '${local_health_path}' for service '${release_name}' must start with '/'"
    exit 1
  fi

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

  app_url="http://${release_name}.127.0.0.1.nip.io:8080"
  has_ingress=$(kubectl -n "${NAMESPACE}" get ingress "${release_name}-ingress" --ignore-not-found 2>/dev/null || true)

  if [[ -z "${has_ingress}" ]]; then
    echo "INFO: Archetype is 'worker'. Skipping HTTP checks for ${release_name}."
    continue
  fi

  echo "INFO: Waiting for Ingress routing to become active for ${release_name}"
  wait_time=0
  while ! curl -fsS "${app_url}${local_health_path}" >/dev/null 2>&1; do
    sleep 2
    wait_time=$((wait_time + 1))
    if [[ ${wait_time} -ge 15 ]]; then echo "ERROR: Ingress routing timeout for ${release_name}"; exit 1; fi
  done

  echo "INFO: Checking ${local_health_path} for ${release_name}"
  if ! curl -fsS "${app_url}${local_health_path}" >/dev/null; then
    echo "ERROR: Health endpoint ${local_health_path} failed for ${release_name}"
    exit 1
  fi
done

echo "INFO: Verification passed"