#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
NAMESPACE="${NAMESPACE:-deployguard}"
RELEASE_NAME="${RELEASE_NAME:-telemetry-collector}"
IMAGE_REPO="${IMAGE_REPO:-telemetry-collector}"
IMAGE_TAG="${IMAGE_TAG:-v1}"

for cmd in docker k3d helm kubectl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'"
    exit 1
  fi
done

echo "INFO: Building image ${IMAGE_REPO}:${IMAGE_TAG}"
docker build -t "${IMAGE_REPO}:${IMAGE_TAG}" "${REPO_ROOT}/app"

echo "INFO: Importing image into k3d cluster ${CLUSTER_NAME}"
k3d image import "${IMAGE_REPO}:${IMAGE_TAG}" -c "${CLUSTER_NAME}"

echo "INFO: Deploying with Helm"
helm upgrade --install "${RELEASE_NAME}" "${REPO_ROOT}/platform/chart" \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  --set image.repository="${IMAGE_REPO}" \
  --set image.tag="${IMAGE_TAG}" \
  --wait

echo "INFO: Deployment completed"
echo "INFO: Run scripts/verify.sh to validate health and metrics"
