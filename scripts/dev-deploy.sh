#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/dev-deploy.sh
# Optional: IMAGE_TAG=v2 ARGO_APP_NAMES=ruby-gateway,python-backend,prometheus SKIP_VERIFY=true ./scripts/dev-deploy.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
ARGO_APP_NAMESPACE="${ARGO_APP_NAMESPACE:-argocd}"
ARGO_APP_NAMES="${ARGO_APP_NAMES:-ruby-gateway,python-backend,sql-database,prometheus}"
ARGO_SYNC_TIMEOUT_SECONDS="${ARGO_SYNC_TIMEOUT_SECONDS:-300}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"
# Platform apps that have no app/ directory to build from
PLATFORM_APPS="${PLATFORM_APPS:-prometheus}"

for cmd in docker k3d kubectl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running. Please start Docker before deploying."
  exit 1
fi

if ! k3d cluster get "${CLUSTER_NAME}" >/dev/null 2>&1; then
  echo "ERROR: k3d cluster '${CLUSTER_NAME}' not found. Did you run ./scripts/setup.sh?"
  exit 1
fi

if [[ -z "${ARGO_APP_NAMES// }" ]]; then
  echo "ERROR: ARGO_APP_NAMES must be a non-empty comma-separated list"
  exit 1
fi

IFS=',' read -r -a ARGO_APPS <<< "${ARGO_APP_NAMES}"
IFS=',' read -r -a PLATFORM_APPS_LIST <<< "${PLATFORM_APPS}"

# Initialize array to collect images for batch import
declare -a IMAGES_TO_IMPORT=()

# Build and import images for all service apps (excluding platform apps)
for app in "${ARGO_APPS[@]}"; do
  app_name="${app// /}"
  is_platform=false
  for platform_app in "${PLATFORM_APPS_LIST[@]}"; do
    if [[ "${app_name}" == "${platform_app// /}" ]]; then
      is_platform=true
      break
    fi
  done
  [[ "${is_platform}" == "true" ]] && continue

  app_context="${REPO_ROOT}/app/${app_name}"
  if [[ ! -d "${app_context}" ]]; then
    echo "ERROR: App directory not found: app/${app_name}"
    exit 1
  fi

  if [[ ! -d "${REPO_ROOT}/platform/charts/${app_name}" ]]; then
    echo "ERROR: Missing generated chart for ${app_name}. Did you run add-service.sh?"
    exit 1
  fi

  echo "INFO: Building image ${app_name}:${IMAGE_TAG}"
  docker build -t "${app_name}:${IMAGE_TAG}" "${app_context}"
  IMAGES_TO_IMPORT+=("${app_name}:${IMAGE_TAG}")
done

if [[ ${#IMAGES_TO_IMPORT[@]} -gt 0 ]]; then
  echo "INFO: Importing images into k3d cluster ${CLUSTER_NAME} in batch..."
  k3d image import "${IMAGES_TO_IMPORT[@]}" -c "${CLUSTER_NAME}"
fi

echo "INFO: Packaging Helm charts for local distribution..."
for app in "${ARGO_APPS[@]}"; do
  app_name="${app// /}"
  if [[ -d "${REPO_ROOT}/platform/charts/${app_name}" ]]; then
    helm package "${REPO_ROOT}/platform/charts/${app_name}" -d "${REPO_ROOT}/platform/charts" >/dev/null
  fi
done
helm repo index "${REPO_ROOT}/platform/charts"

echo "INFO: Starting local Helm repository server..."
docker stop deployguard-helm-server >/dev/null 2>&1 || true
docker run -d --rm --name deployguard-helm-server -p 8081:80 -v "${REPO_ROOT}/platform/charts:/usr/share/nginx/html" nginx:alpine >/dev/null

echo "INFO: Registering ArgoCD applications..."
for app in "${ARGO_APPS[@]}"; do
  app_name="${app// /}"
  manifest="${REPO_ROOT}/platform/gitops/${app_name}.yaml"
  if [[ -f "${manifest}" ]]; then
    kubectl apply -f "${manifest}" >/dev/null
  fi
done

for app in "${ARGO_APPS[@]}"; do
  app_name="${app// /}"

  if [[ -z "${app_name}" ]]; then
    echo "ERROR: ARGO_APP_NAMES contains an empty entry"
    exit 1
  fi

  if ! kubectl -n "${ARGO_APP_NAMESPACE}" get application "${app_name}" >/dev/null 2>&1; then
    echo "ERROR: ArgoCD Application '${app_name}' not found in namespace '${ARGO_APP_NAMESPACE}'"
    echo "ERROR: Run ./scripts/bootstrap-platform.sh first"
    exit 1
  fi

  echo "INFO: Triggering ArgoCD sync for ${app_name}"
  kubectl -n "${ARGO_APP_NAMESPACE}" patch application "${app_name}" \
    --type merge \
    -p '{"operation":{"sync":{"prune":true}}}' >/dev/null

  echo "INFO: Waiting for ArgoCD sync status for ${app_name}"
  if ! kubectl -n "${ARGO_APP_NAMESPACE}" wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${app_name}" \
    --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"; then
    echo "ERROR: ArgoCD sync timed out for ${app_name}. Run 'kubectl -n ${ARGO_APP_NAMESPACE} get application ${app_name} -o yaml' to debug."
    exit 1
  fi

  echo "INFO: Waiting for ArgoCD health status for ${app_name}"
  if ! kubectl -n "${ARGO_APP_NAMESPACE}" wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${app_name}" \
    --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"; then
    echo "ERROR: ArgoCD health check timed out for ${app_name}. Check the pods: 'kubectl -n deployguard get pods -l app=${app_name}'"
    exit 1
  fi
done

echo "INFO: ArgoCD sync completed"

if [[ "${SKIP_VERIFY}" == "true" ]]; then
  echo "INFO: SKIP_VERIFY=true, skipping verification"
else
  echo "INFO: Running verification"
  VERIFY_RELEASE_NAMES="${VERIFY_RELEASE_NAMES:-}"
  if [[ -z "${VERIFY_RELEASE_NAMES// }" ]]; then
    release_list=()
    for app in "${ARGO_APPS[@]}"; do
      app_name="${app// /}"
      is_platform=false
      for platform_app in "${PLATFORM_APPS_LIST[@]}"; do
        if [[ "${app_name}" == "${platform_app// /}" ]]; then
          is_platform=true
          break
        fi
      done
      if [[ "${is_platform}" == "false" ]]; then
        release_list+=("${app_name}")
      fi
    done
    if [[ ${#release_list[@]} -eq 0 ]]; then
      echo "ERROR: No service releases found for verification"
      exit 1
    fi
    VERIFY_RELEASE_NAMES="$(IFS=','; echo "${release_list[*]}")"
  fi

  VERIFY_PROM_EXPECTED_JOBS="${VERIFY_PROM_EXPECTED_JOBS:-${ARGO_APP_NAMES}}"

  RELEASE_NAMES="${VERIFY_RELEASE_NAMES}" \
  PROM_EXPECTED_JOBS="${VERIFY_PROM_EXPECTED_JOBS}" \
  EXPECTED_METRIC="${EXPECTED_METRIC:-}" \
  HEALTH_PATH="${HEALTH_PATH:-/health}" \
  METRICS_PATH="${METRICS_PATH:-/metrics}" \
  "${REPO_ROOT}/scripts/verify.sh"
fi
