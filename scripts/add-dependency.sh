#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${1:-}"
shift || true

REPO_URL=""
CHART_NAME=""
TARGET_REVISION="HEAD"
NAMESPACE="deployguard"
SECRET_NAME=""
declare -a SECRET_KVS=()
declare -a SET_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO_URL="$2"; shift 2 ;;
    --chart) CHART_NAME="$2"; shift 2 ;;
    --version) TARGET_REVISION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --secret) 
      SECRET_NAME="$2"
      SECRET_KVS+=("$3")
      shift 3 
      ;;
    --set) SET_ARGS+=("$2"); shift 2 ;;
    *) echo "ERROR: Unknown argument '$1'"; exit 1 ;;
  esac
done

if [[ -z "${APP_NAME}" || -z "${REPO_URL}" || -z "${CHART_NAME}" ]]; then
  echo "Usage: ./scripts/add-dependency.sh <app-name> --repo <url> --chart <name> [--secret <secret-name> <key=val>] [--set <key=val>]"
  exit 1
fi

GITOPS_FILE="platform/gitops/${APP_NAME}.yaml"
mkdir -p platform/gitops

# 1. Create Generic K8s Secret if requested
if [[ -n "${SECRET_NAME}" ]]; then
  SECRET_FILE="platform/gitops/${APP_NAME}-secret.yaml"
  cat > "${SECRET_FILE}" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
data:
EOF
  for kv in "${SECRET_KVS[@]}"; do
    key="${kv%%=*}"
    val="${kv#*=}"
    b64_val=$(echo -n "${val}" | base64)
    echo "  ${key}: ${b64_val}" >> "${SECRET_FILE}"
  done
  echo "INFO: Created Secret manifest for ${APP_NAME} at ${SECRET_FILE}"
fi

# 2. Create ArgoCD Application
cat > "${GITOPS_FILE}" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${APP_NAME}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: ${REPO_URL}
    chart: ${CHART_NAME}
    targetRevision: "${TARGET_REVISION}"
    helm:
      releaseName: ${APP_NAME}
EOF

if [[ ${#SET_ARGS[@]} -gt 0 ]]; then
  echo "      parameters:" >> "${GITOPS_FILE}"
  for arg in "${SET_ARGS[@]}"; do
    key="${arg%%=*}"
    val="${arg#*=}"
    echo "        - name: ${key}" >> "${GITOPS_FILE}"
    echo "          value: ${val}" >> "${GITOPS_FILE}"
  done
fi

cat >> "${GITOPS_FILE}" <<EOF
  destination:
    server: https://kubernetes.default.svc
    namespace: ${NAMESPACE}
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
EOF

echo "INFO: Created GitOps dependency for ${APP_NAME}"