#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/dev-deploy.sh
# Optional: IMAGE_TAG=v2 ARGO_APP_NAME=telemetry-collector ./scripts/dev-deploy.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
IMAGE_REPO="${IMAGE_REPO:-telemetry-collector}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
ARGO_APP_NAMESPACE="${ARGO_APP_NAMESPACE:-argocd}"
ARGO_APP_NAME="${ARGO_APP_NAME:-telemetry-collector}"
ARGO_SYNC_TIMEOUT_SECONDS="${ARGO_SYNC_TIMEOUT_SECONDS:-180}"

for cmd in docker k3d kubectl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

echo "INFO: Building image ${IMAGE_REPO}:${IMAGE_TAG}"
docker build -t "${IMAGE_REPO}:${IMAGE_TAG}" "${REPO_ROOT}/app"

echo "INFO: Importing image into k3d cluster ${CLUSTER_NAME}"
k3d image import "${IMAGE_REPO}:${IMAGE_TAG}" -c "${CLUSTER_NAME}"

if ! kubectl -n "${ARGO_APP_NAMESPACE}" get application "${ARGO_APP_NAME}" >/dev/null 2>&1; then
  echo "ERROR: ArgoCD Application '${ARGO_APP_NAME}' not found in namespace '${ARGO_APP_NAMESPACE}'"
  echo "ERROR: Run ./scripts/bootstrap-platform.sh first"
  exit 1
fi

echo "INFO: Triggering ArgoCD sync for ${ARGO_APP_NAME}"
kubectl -n "${ARGO_APP_NAMESPACE}" patch application "${ARGO_APP_NAME}" \
  --type merge \
  -p '{"operation":{"sync":{"prune":true}}}' >/dev/null

echo "INFO: Waiting for ArgoCD sync status"
kubectl -n "${ARGO_APP_NAMESPACE}" wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${ARGO_APP_NAME}" \
  --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"

echo "INFO: Waiting for ArgoCD health status"
kubectl -n "${ARGO_APP_NAMESPACE}" wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${ARGO_APP_NAME}" \
  --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"

echo "INFO: ArgoCD sync completed"
echo "INFO: Run scripts/verify.sh to validate health and metrics"
