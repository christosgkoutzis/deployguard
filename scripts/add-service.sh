#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${1:-}"
shift || true

IMAGE_REPO="${SERVICE_NAME}"
IMAGE_TAG="v1"
CONTAINER_PORT="8000"
SERVICE_PORT="80"
HEALTH_PATH="/health"
METRICS_PATH="/metrics"
NAMESPACE="deployguard"
PERSISTENCE_ENABLED="false"
STORAGE_SIZE=""
STORAGE_MOUNT="/data"

APP_DIR="${REPO_ROOT}/app/${SERVICE_NAME}"
GITOPS_FILE="${REPO_ROOT}/platform/gitops/${SERVICE_NAME}.yaml"

if [[ -z "${SERVICE_NAME}" ]]; then
  echo "ERROR: Missing service name"
  exit 1
fi

# 1. Gather Environment Variables (Hybrid Approach)
declare -A ENV_VARS
ENV_VARS["APP_NAME"]="${SERVICE_NAME}"

# A. Read custom env_file if declared in deployguard.yaml
ENV_FILE=$(yq ".services[] | select(.name == \"$SERVICE_NAME\") | .env_file" "$REPO_ROOT/deployguard.yaml" 2>/dev/null | grep -v "null" || true)
if [[ -n "$ENV_FILE" && -f "$APP_DIR/$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ $key =~ ^#.*$ ]] || [[ -z $key ]] && continue
    value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    ENV_VARS["$key"]="$value"
  done < "$APP_DIR/$ENV_FILE"
fi

# B. Read inline overrides from deployguard.yaml
ENV_LEN=$(yq ".services[] | select(.name == \"$SERVICE_NAME\") | .env | length" "$REPO_ROOT/deployguard.yaml" 2>/dev/null || echo 0)
if [[ "$ENV_LEN" =~ ^[0-9]+$ ]] && [[ "$ENV_LEN" -gt 0 ]]; then
  for i in $(seq 0 $((ENV_LEN-1))); do
    KV=$(yq ".services[] | select(.name == \"$SERVICE_NAME\") | .env[$i]" "$REPO_ROOT/deployguard.yaml")
    key="${KV%%=*}"
    value="${KV#*=}"
    value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    ENV_VARS["$key"]="$value"
  done
fi

INIT_COMMAND="${ENV_VARS[INIT_COMMAND]:-}"
unset ENV_VARS[INIT_COMMAND] # Remove from standard env list so it's not injected into the app container

# 2. Build the Values block for the Universal Chart
VALUES_YAML="image:
  repository: ${IMAGE_REPO}
  tag: ${IMAGE_TAG}
service:
  port: ${SERVICE_PORT}
  targetPort: ${CONTAINER_PORT}
ingress:
  host: ${SERVICE_NAME}.127.0.0.1.nip.io
health:
  path: ${HEALTH_PATH}
metrics:
  path: ${METRICS_PATH}
persistence:
  enabled: ${PERSISTENCE_ENABLED}
  size: \"${STORAGE_SIZE}\"
  mountPath: \"${STORAGE_MOUNT}\"
initCommand: \"${INIT_COMMAND}\""

if [[ ${#ENV_VARS[@]} -gt 0 ]]; then
  VALUES_YAML="${VALUES_YAML}
env:"
  for key in "${!ENV_VARS[@]}"; do
    VALUES_YAML="${VALUES_YAML}
  ${key}: \"${ENV_VARS[$key]}\""
  done
fi

# 3. Scaffold ArgoCD Application referencing Universal Chart
cat > "${GITOPS_FILE}" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${SERVICE_NAME}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: http://host.k3d.internal:8081
    chart: universal-chart
    targetRevision: 0.1.0
    helm:
      releaseName: ${SERVICE_NAME}
      values: |
$(echo "$VALUES_YAML" | sed 's/^/        /')
  destination:
    server: https://kubernetes.default.svc
    namespace: ${NAMESPACE}
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
EOF

echo "INFO: Configured Universal GitOps app for ${SERVICE_NAME}"