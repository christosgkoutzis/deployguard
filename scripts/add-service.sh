#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${1:-}"
shift || true

IMAGE_REPO="${SERVICE_NAME}"
IMAGE_TAG="v1"
SERVICE_PORT="80"
NAMESPACE="deployguard"
PERSISTENCE_ENABLED="false"
STORAGE_SIZE=""
STORAGE_MOUNT="/data"

TOPOLOGY_FILE="${TOPOLOGY_FILE:-${REPO_ROOT}/deployguard.yaml}"
YQ_BASE=".services[] | select(.name == \"$SERVICE_NAME\")"

CONTAINER_PORT=$(yq "$YQ_BASE | .port // 8000" "$TOPOLOGY_FILE" 2>/dev/null | sed 's/"//g' || echo "8000")
CONTAINER_PORT="${CONTAINER_PORT:-8000}"

HEALTH_PATH=$(yq "$YQ_BASE | .health_endpoint // \"/health\"" "$TOPOLOGY_FILE" 2>/dev/null | sed 's/"//g' || echo "/health")
HEALTH_PATH="${HEALTH_PATH:-/health}"
WORKLOAD_TYPE=$(yq "$YQ_BASE | .type" "$TOPOLOGY_FILE" 2>/dev/null | grep -v "null" || true)
WORKLOAD_TYPE="${WORKLOAD_TYPE:-webservice}"

CUSTOM_BUILD_PATH=$(yq "$YQ_BASE | .build_path // \"\"" "$TOPOLOGY_FILE" 2>/dev/null | sed 's/"//g')
if [[ -n "$CUSTOM_BUILD_PATH" && "$CUSTOM_BUILD_PATH" != "null" && "$CUSTOM_BUILD_PATH" != "" ]]; then
  APP_DIR="${REPO_ROOT}/${CUSTOM_BUILD_PATH}"
elif [[ "${WORKLOAD_TYPE}" == "test" ]]; then
  APP_DIR="${REPO_ROOT}/tests/${SERVICE_NAME}"
else
  APP_DIR="${REPO_ROOT}/services/${SERVICE_NAME}"
fi

GITOPS_FILE="${REPO_ROOT}/platform/gitops/${SERVICE_NAME}.yaml"

mkdir -p "${REPO_ROOT}/platform/gitops"

if [[ -z "${SERVICE_NAME}" ]]; then
  echo "ERROR: Missing service name"
  exit 1
fi

# 1. Gather Environment Variables (Hybrid Approach)
declare -A ENV_VARS
ENV_VARS["APP_NAME"]="${SERVICE_NAME}"

# A. Read custom env_file if declared in deployguard.yaml
ENV_FILE=$(yq "$YQ_BASE | .env_file" "$TOPOLOGY_FILE" 2>/dev/null | grep -v "null" || true)
if [[ -n "$ENV_FILE" && -f "$APP_DIR/$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ $key =~ ^#.*$ ]] || [[ -z $key ]] && continue
    value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    ENV_VARS["$key"]="$value"
  done < "$APP_DIR/$ENV_FILE"
fi

# B. Read inline overrides from deployguard.yaml
ENV_LEN=$(yq "$YQ_BASE | .env | length" "$TOPOLOGY_FILE" 2>/dev/null || echo 0)
if [[ "$ENV_LEN" =~ ^[0-9]+$ ]] && [[ "$ENV_LEN" -gt 0 ]]; then
  for i in $(seq 0 $((ENV_LEN-1))); do
    KV=$(yq "$YQ_BASE | .env[$i]" "$TOPOLOGY_FILE")
    key="${KV%%=*}"
    value="${KV#*=}"
    value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    ENV_VARS["$key"]="$value"
  done
fi

INIT_COMMAND="${ENV_VARS[INIT_COMMAND]:-}"
unset ENV_VARS[INIT_COMMAND] # Remove from standard env list so it's not injected into the app container

RESOURCES_YAML=$(yq "$YQ_BASE | .resources" "$TOPOLOGY_FILE" 2>/dev/null | grep -v "null" || true)
WORKLOAD_TYPE=$(yq "$YQ_BASE | .type" "$TOPOLOGY_FILE" 2>/dev/null | grep -v "null" || true)
WORKLOAD_TYPE="${WORKLOAD_TYPE:-webservice}"

# 2. Build the Values block natively using AST manipulation (SRE standard)
VALUES_FILE=$(mktemp)
cat > "$VALUES_FILE" <<EOF
workloadType: "${WORKLOAD_TYPE}"
image:
  repository: "${IMAGE_REPO}"
  tag: "${IMAGE_TAG}"
service:
  port: ${SERVICE_PORT}
  targetPort: ${CONTAINER_PORT}
ingress:
  host: "${SERVICE_NAME}.${CLUSTER_DOMAIN}"
health:
  path: "${HEALTH_PATH}"
persistence:
  enabled: ${PERSISTENCE_ENABLED}
  size: "${STORAGE_SIZE}"
  mountPath: "${STORAGE_MOUNT}"
initCommand: "${INIT_COMMAND}"
EOF

if [[ ${#ENV_VARS[@]} -gt 0 ]]; then
  for key in "${!ENV_VARS[@]}"; do
    export ENV_VAL="${ENV_VARS[$key]}"
    yq -i ".env.\"${key}\" = env(ENV_VAL)" "$VALUES_FILE"
  done
fi

VALUES_YAML=$(cat "$VALUES_FILE")
rm "$VALUES_FILE"

if [[ -n "$RESOURCES_YAML" ]]; then
  VALUES_YAML="${VALUES_YAML}
resources:
$(echo "$RESOURCES_YAML" | sed 's/^/  /')"
fi

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