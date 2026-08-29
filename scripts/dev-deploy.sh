#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
ARGO_APP_NAMESPACE="${ARGO_APP_NAMESPACE:-argocd}"
ARGO_SYNC_TIMEOUT_SECONDS="${ARGO_SYNC_TIMEOUT_SECONDS:-180}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"
TOPOLOGY_FILE="${TOPOLOGY_FILE:-${REPO_ROOT}/deployguard.yaml}"

declare -a IMAGES_TO_IMPORT=()
for app_context in "${REPO_ROOT}/services/"*; do
  if [[ -d "$app_context" ]]; then
    app_name=$(basename "$app_context")
    echo "INFO: Building image ${app_name}:${IMAGE_TAG}"
    docker build -t "${app_name}:${IMAGE_TAG}" "${app_context}"
    IMAGES_TO_IMPORT+=("${app_name}:${IMAGE_TAG}")
  fi
done
for app_context in "${REPO_ROOT}/tests/"*; do
  if [[ -d "$app_context" ]]; then
    app_name=$(basename "$app_context")
    echo "INFO: Building image ${app_name}:${IMAGE_TAG}"
    docker build -t "${app_name}:${IMAGE_TAG}" "${app_context}"
    IMAGES_TO_IMPORT+=("${app_name}:${IMAGE_TAG}")
  fi
done

if [[ ${#IMAGES_TO_IMPORT[@]} -gt 0 ]]; then
  echo "INFO: Importing images into k3d cluster ${CLUSTER_NAME} in batch..."
  k3d image import "${IMAGES_TO_IMPORT[@]}" -c "${CLUSTER_NAME}"
fi

echo "INFO: Packaging Modular Helm charts for local distribution..."
find "${REPO_ROOT}/platform/charts" "${REPO_ROOT}/platform/dependencies" -maxdepth 2 -name "Chart.yaml" | while read -r chart_file; do
  chart_dir=$(dirname "$chart_file")
  helm package -u "$chart_dir" -d "${REPO_ROOT}/platform/charts-dist" >/dev/null
done
helm repo index "${REPO_ROOT}/platform/charts-dist"

echo "INFO: Starting local Helm repository server..."
docker rm -f deployguard-helm-server >/dev/null 2>&1 || true
docker run -d --rm --name deployguard-helm-server -p 8081:80 -v "${REPO_ROOT}/platform/charts-dist:/usr/share/nginx/html" nginx:alpine >/dev/null

echo "INFO: Waiting for Helm repository server to be ready..."
wait_time=0
while ! curl -fsS http://127.0.0.1:8081/index.yaml >/dev/null 2>&1; do
  sleep 1
  wait_time=$((wait_time + 1))
  if [[ ${wait_time} -ge 15 ]]; then echo "ERROR: Helm server failed to start in time"; exit 1; fi
done

echo "INFO: Registering ArgoCD applications and secrets..."
kubectl apply -f "${REPO_ROOT}/platform/gitops/" >/dev/null

echo "INFO: Triggering ArgoCD syncs..."
for app_yaml in "${REPO_ROOT}/platform/gitops/"*.yaml; do
  app_name=$(basename "$app_yaml" .yaml)
  kubectl -n "${ARGO_APP_NAMESPACE}" patch application "${app_name}" \
    --type merge \
    -p '{"operation":{"sync":{"prune":true}}}' >/dev/null || true
done

echo "INFO: Waiting for ArgoCD syncs to complete..."
sleep 5 # Give ArgoCD time to register the patch

for app_yaml in "${REPO_ROOT}/platform/gitops/"*.yaml; do
  app_name=$(basename "$app_yaml" .yaml)
  echo "INFO: Waiting for sync: ${app_name}"
  if ! kubectl -n "${ARGO_APP_NAMESPACE}" wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${app_name}" \
    --timeout="${ARGO_SYNC_TIMEOUT_SECONDS}s"; then
    echo "ERROR: ArgoCD sync failed for ${app_name}"
    exit 1
  fi
done

echo "INFO: Dev Deploy completed!"
