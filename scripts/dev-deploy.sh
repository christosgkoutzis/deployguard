#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/dev-deploy.sh
# Optional: IMAGE_TAG=v2 IMAGE_CONTEXT=app ARGO_APP_NAMES=telemetry-collector,prometheus SKIP_VERIFY=true ./scripts/dev-deploy.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
IMAGE_REPO="${IMAGE_REPO:-telemetry-collector}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
IMAGE_CONTEXT="${IMAGE_CONTEXT:-app}"
ARGO_APP_NAMESPACE="${ARGO_APP_NAMESPACE:-argocd}"
ARGO_APP_NAMES="${ARGO_APP_NAMES:-telemetry-collector,prometheus}"
ARGO_SYNC_TIMEOUT_SECONDS="${ARGO_SYNC_TIMEOUT_SECONDS:-180}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"

for cmd in docker k3d kubectl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

if [[ "${IMAGE_CONTEXT}" = /* ]]; then
  BUILD_CONTEXT="${IMAGE_CONTEXT}"
else
  BUILD_CONTEXT="${REPO_ROOT}/${IMAGE_CONTEXT}"
fi

if [[ ! -d "${BUILD_CONTEXT}" ]]; then
  echo "ERROR: Build context does not exist: ${BUILD_CONTEXT}"
  exit 1
fi

echo "INFO: Building image ${IMAGE_REPO}:${IMAGE_TAG}"
docker build -t "${IMAGE_REPO}:${IMAGE_TAG}" "${BUILD_CONTEXT}"

echo "INFO: Importing image into k3d cluster ${CLUSTER_NAME}"
k3d image import "${IMAGE_REPO}:${IMAGE_TAG}" -c "${CLUSTER_NAME}"

if [[ -z "${ARGO_APP_NAMES// }" ]]; then
  echo "ERROR: ARGO_APP_NAMES must be a non-empty comma-separated list"
  exit 1
fi

IFS=',' read -r -a ARGO_APPS <<< "${ARGO_APP_NAMES}"

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
  kubectl -n "${ARGO_APP_NAMESPACE}" wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${app_name}" \
    --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"

  echo "INFO: Waiting for ArgoCD health status for ${app_name}"
  kubectl -n "${ARGO_APP_NAMESPACE}" wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${app_name}" \
    --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"
done

echo "INFO: ArgoCD sync completed"

if [[ "${SKIP_VERIFY}" == "true" ]]; then
  echo "INFO: SKIP_VERIFY=true, skipping verification"
else
  echo "INFO: Running verification"
  "${REPO_ROOT}/scripts/verify.sh"
fi
