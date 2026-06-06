#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/add-service.sh <service-name>

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${1:-}"

DEFAULT_NAMESPACE="deployguard"
DEFAULT_REPO_URL="https://github.com/christosgkoutzis/deployguard.git"
DEFAULT_TARGET_REVISION="master"

if [[ -z "${SERVICE_NAME}" ]]; then
  echo "ERROR: Missing service name"
  echo "Usage: ./scripts/add-service.sh <service-name>"
  exit 1
fi

if [[ ! "${SERVICE_NAME}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
  echo "ERROR: Service name must be lowercase letters, numbers, and hyphens only"
  exit 1
fi

APP_DIR="${REPO_ROOT}/app/${SERVICE_NAME}"
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

if [[ ! -f "${APP_DIR}/requirements.txt" ]]; then
  echo "ERROR: Missing required file: app/${SERVICE_NAME}/requirements.txt"
  exit 1
fi

if [[ ! -f "${APP_DIR}/main.py" ]]; then
  echo "ERROR: Missing required file: app/${SERVICE_NAME}/main.py"
  exit 1
fi

if ! grep -R --exclude-dir='__pycache__' -E '(/health|health_check|healthcheck)' "${APP_DIR}" >/dev/null 2>&1; then
  echo "ERROR: Service must expose a health endpoint under app/${SERVICE_NAME}"
  exit 1
fi

if ! grep -R --exclude-dir='__pycache__' -E '(/metrics|prometheus|Counter|Histogram|Summary|Gauge)' "${APP_DIR}" >/dev/null 2>&1; then
  echo "ERROR: Service must expose Prometheus metrics under app/${SERVICE_NAME}"
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
  repository: ${SERVICE_NAME}
  tag: v1
  pullPolicy: Never

tenant:
  id: "Alpha-Tenant"
  label: "alpha"

service:
  port: 80
  targetPort: 8000

resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "250m"
    memory: "256Mi"

readinessProbe:
  path: /health
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3

livenessProbe:
  path: /health
  initialDelaySeconds: 15
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3
EOF

cat > "${CHART_TEMPLATES_DIR}/collector.yaml" <<'EOF'
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
    prometheus.io/path: /metrics
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
    repoURL: ${DEFAULT_REPO_URL}
    targetRevision: ${DEFAULT_TARGET_REVISION}
    path: platform/charts/${SERVICE_NAME}
    helm:
      releaseName: ${SERVICE_NAME}
  destination:
    server: https://kubernetes.default.svc
    namespace: ${DEFAULT_NAMESPACE}
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