#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./scripts/add-service.sh <service-name> \
#   [--image-repo <repo>] \
#   [--image-tag <tag>] \
#   [--container-port <port>] \
#   [--service-port <port>] \
#   [--health-path <path>] \
#   [--metrics-path <path>]

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${1:-}"
shift || true

DEFAULT_NAMESPACE="deployguard"
DEFAULT_REPO_URL="https://github.com/christosgkoutzis/deployguard.git"
DEFAULT_TARGET_REVISION="master"

IMAGE_REPO="${SERVICE_NAME}"
IMAGE_TAG="v1"
CONTAINER_PORT="8000"
SERVICE_PORT="80"
HEALTH_PATH="/health"
METRICS_PATH="/metrics"
NAMESPACE="${DEFAULT_NAMESPACE}"
REPO_URL="${DEFAULT_REPO_URL}"
TARGET_REVISION="${DEFAULT_TARGET_REVISION}"

if [[ -z "${SERVICE_NAME}" ]]; then
  echo "ERROR: Missing service name"
  echo "Usage: ./scripts/add-service.sh <service-name> [--image-repo <repo>] [--image-tag <tag>] [--container-port <port>] [--service-port <port>] [--health-path <path>] [--metrics-path <path>]"
  exit 1
fi

if [[ ! "${SERVICE_NAME}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
  echo "ERROR: Service name must be lowercase letters, numbers, and hyphens only"
  exit 1
fi

APP_DIR="${REPO_ROOT}/app/${SERVICE_NAME}"

if [[ -f "${APP_DIR}/service.contract.env" ]]; then
  # shellcheck disable=SC1090
  source "${APP_DIR}/service.contract.env"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image-repo)
      IMAGE_REPO="${2:-}"
      shift 2
      ;;
    --image-tag)
      IMAGE_TAG="${2:-}"
      shift 2
      ;;
    --container-port)
      CONTAINER_PORT="${2:-}"
      shift 2
      ;;
    --service-port)
      SERVICE_PORT="${2:-}"
      shift 2
      ;;
    --health-path)
      HEALTH_PATH="${2:-}"
      shift 2
      ;;
    --metrics-path)
      METRICS_PATH="${2:-}"
      shift 2
      ;;
    --namespace)
      NAMESPACE="${2:-}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --target-revision)
      TARGET_REVISION="${2:-}"
      shift 2
      ;;
    *)
      echo "ERROR: Unknown argument '$1'"
      exit 1
      ;;
  esac
done

if [[ ! "${CONTAINER_PORT}" =~ ^[0-9]+$ ]] || [[ ! "${SERVICE_PORT}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --container-port and --service-port must be numeric"
  exit 1
fi

if [[ "${HEALTH_PATH}" != /* ]] || [[ "${METRICS_PATH}" != /* ]]; then
  echo "ERROR: --health-path and --metrics-path must start with '/'"
  exit 1
fi

CHART_DIR="${REPO_ROOT}/platform/charts/${SERVICE_NAME}"
CHART_TEMPLATES_DIR="${CHART_DIR}/templates"
GITOPS_FILE="${REPO_ROOT}/platform/gitops/${SERVICE_NAME}.yaml"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "ERROR: Service directory not found: app/${SERVICE_NAME}"
  exit 1
fi

if [[ -d "${CHART_DIR}" ]]; then
  echo "ERROR: Chart directory already exists: platform/charts/${SERVICE_NAME}"
  exit 1
fi

if [[ -f "${GITOPS_FILE}" ]]; then
  echo "ERROR: GitOps manifest already exists: platform/gitops/${SERVICE_NAME}.yaml"
  exit 1
fi

if [[ ! -f "${APP_DIR}/Dockerfile" ]]; then
  echo "ERROR: Missing required file: app/${SERVICE_NAME}/Dockerfile"
  exit 1
fi

mkdir -p "${CHART_TEMPLATES_DIR}"

cat > "${CHART_DIR}/Chart.yaml" <<EOF
apiVersion: v2
name: ${SERVICE_NAME}
description: Helm chart for the ${SERVICE_NAME} application
type: application
version: 0.1.0
appVersion: "1.0.0"
EOF

cat > "${CHART_DIR}/values.yaml" <<EOF
replicaCount: 2
image:
  repository: ${IMAGE_REPO}
  tag: ${IMAGE_TAG}
  pullPolicy: Never

tenant:
  id: "Alpha-Tenant"
  label: "alpha"

service:
  port: ${SERVICE_PORT}
  targetPort: ${CONTAINER_PORT}

resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "250m"
    memory: "256Mi"

readinessProbe:
  path: ${HEALTH_PATH}
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3

livenessProbe:
  path: ${HEALTH_PATH}
  initialDelaySeconds: 15
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3

metrics:
  path: ${METRICS_PATH}
EOF

cat > "${CHART_TEMPLATES_DIR}/service.yaml" <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
  labels:
    app: {{ .Release.Name }}
    tenant: {{ .Values.tenant.label }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}
    spec:
      containers:
      - name: {{ .Release.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        imagePullPolicy: {{ .Values.image.pullPolicy }}
        resources:
          requests:
            cpu: {{ .Values.resources.requests.cpu | quote }}
            memory: {{ .Values.resources.requests.memory | quote }}
          limits:
            cpu: {{ .Values.resources.limits.cpu | quote }}
            memory: {{ .Values.resources.limits.memory | quote }}
        ports:
        - containerPort: {{ .Values.service.targetPort }}
        readinessProbe:
          httpGet:
            path: {{ .Values.readinessProbe.path }}
            port: {{ .Values.service.targetPort }}
          initialDelaySeconds: {{ .Values.readinessProbe.initialDelaySeconds }}
          periodSeconds: {{ .Values.readinessProbe.periodSeconds }}
          timeoutSeconds: {{ .Values.readinessProbe.timeoutSeconds }}
          failureThreshold: {{ .Values.readinessProbe.failureThreshold }}
        livenessProbe:
          httpGet:
            path: {{ .Values.livenessProbe.path }}
            port: {{ .Values.service.targetPort }}
          initialDelaySeconds: {{ .Values.livenessProbe.initialDelaySeconds }}
          periodSeconds: {{ .Values.livenessProbe.periodSeconds }}
          timeoutSeconds: {{ .Values.livenessProbe.timeoutSeconds }}
          failureThreshold: {{ .Values.livenessProbe.failureThreshold }}
        env:
        - name: TENANT_ID
          value: {{ .Values.tenant.id | quote }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-service
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/path: {{ .Values.metrics.path | quote }}
    prometheus.io/port: {{ .Values.service.port | quote }}
    prometheus.io/job: {{ .Release.Name | quote }}
spec:
  selector:
    app: {{ .Release.Name }}
  ports:
    - protocol: TCP
      port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
  type: ClusterIP
EOF

cat > "${GITOPS_FILE}" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${SERVICE_NAME}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: ${REPO_URL}
    targetRevision: ${TARGET_REVISION}
    path: platform/charts/${SERVICE_NAME}
    helm:
      releaseName: ${SERVICE_NAME}
  destination:
    server: https://kubernetes.default.svc
    namespace: ${NAMESPACE}
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
EOF

if ! command -v helm >/dev/null 2>&1; then
  echo "ERROR: helm is required for scaffold validation"
  exit 1
fi

helm template "${SERVICE_NAME}" "${CHART_DIR}" >/dev/null

echo "INFO: Created chart: platform/charts/${SERVICE_NAME}"
echo "INFO: Created ArgoCD app: platform/gitops/${SERVICE_NAME}.yaml"
echo "INFO: Scaffold validation passed"