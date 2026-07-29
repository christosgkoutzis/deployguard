#!/usr/bin/env bash
set -euo pipefail
# Usage: ./scripts/dev-deploy.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-control-plane-cluster}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
ARGO_APP_NAMESPACE="${ARGO_APP_NAMESPACE:-argocd}"
ARGO_APP_NAMES="${ARGO_APP_NAMES:-ruby-gateway,python-backend,sql-database}"
ARGO_SYNC_TIMEOUT_SECONDS="${ARGO_SYNC_TIMEOUT_SECONDS:-180}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"

MOCK_MEMORY_LIMIT="${MOCK_MEMORY_LIMIT:-256Mi}"
MOCK_JAVA_OPTS="${MOCK_JAVA_OPTS:--Xmx128m}"

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

declare -a SANITIZED_APPS=()
for app in "${ARGO_APPS[@]}"; do
  app_name="${app// /}"
  [[ -n "${app_name}" ]] && SANITIZED_APPS+=("${app_name}")
done

MOCK_APP_NAMES="${MOCK_APP_NAMES:-}"
declare -a MOCK_APPS_LIST=()
if [[ -n "${MOCK_APP_NAMES// }" ]]; then
  IFS=',' read -r -a raw_mocks <<< "${MOCK_APP_NAMES}"
  for m in "${raw_mocks[@]}"; do
    m_name="${m// /}"
    [[ -n "${m_name}" ]] && MOCK_APPS_LIST+=("${m_name}")
  done
fi

for mock_name in "${MOCK_APPS_LIST[@]}"; do
  MOCK_DIR="${REPO_ROOT}/platform/mocks/${mock_name}"
  if [[ ! -d "${MOCK_DIR}" ]]; then
    echo "ERROR: Mock directory not found: platform/mocks/${mock_name}"
    exit 1
  fi

  CHART_DIR="${REPO_ROOT}/platform/charts/${mock_name}"
  mkdir -p "${CHART_DIR}/templates"

  cat > "${CHART_DIR}/Chart.yaml" <<EOF
apiVersion: v2
name: ${mock_name}
description: WireMock chart for ${mock_name}
type: application
version: 0.1.0
EOF

  cat > "${CHART_DIR}/templates/configmap.yaml" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-mocks
data:
EOF
  for json_file in "${MOCK_DIR}"/*.json; do
    if [[ -f "${json_file}" ]]; then
      echo "  $(basename "${json_file}"): |" >> "${CHART_DIR}/templates/configmap.yaml"
      sed 's/^/    /' "${json_file}" >> "${CHART_DIR}/templates/configmap.yaml"
      printf '\n' >> "${CHART_DIR}/templates/configmap.yaml"
    fi
  done

  cat > "${CHART_DIR}/templates/wiremock.yaml" <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
  labels:
    app: {{ .Release.Name }}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}
    spec:
      containers:
      - name: wiremock
        image: wiremock/wiremock:3.3.1
        args: ["--global-response-templating", "--disable-gzip"]
        env:
        - name: JAVA_OPTS
          value: "${MOCK_JAVA_OPTS}"
        resources:
          limits:
            memory: "${MOCK_MEMORY_LIMIT}"
          requests:
            memory: 128Mi
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: mock-data
          mountPath: /home/wiremock/mappings
        readinessProbe:
          httpGet:
            path: /__admin/
            port: 8080
          initialDelaySeconds: 2
      volumes:
      - name: mock-data
        configMap:
          name: {{ .Release.Name }}-mocks
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-service
spec:
  selector:
    app: {{ .Release.Name }}
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Release.Name }}-ingress
spec:
  ingressClassName: traefik
  rules:
    - host: {{ .Release.Name }}.127.0.0.1.nip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Release.Name }}-service
                port:
                  number: 80
EOF

  cat > "${REPO_ROOT}/platform/gitops/${mock_name}.yaml" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ${mock_name}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: http://host.k3d.internal:8081
    chart: ${mock_name}
    targetRevision: 0.1.0
    helm:
      releaseName: ${mock_name}
  destination:
    server: https://kubernetes.default.svc
    namespace: deployguard
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
EOF
done

declare -a IMAGES_TO_IMPORT=()
for app_name in "${SANITIZED_APPS[@]}"; do
  is_platform_app "${app_name}" && continue

  is_mock="false"
  for m in "${MOCK_APPS_LIST[@]}"; do
    [[ "${app_name}" == "${m}" ]] && is_mock="true" && break
  done
  [[ "${is_mock}" == "true" ]] && continue

  app_context="${REPO_ROOT}/app/${app_name}"
  if [[ ! -d "${app_context}" ]]; then
    echo "ERROR: App directory not found: app/${app_name}"
    exit 1
  fi

  if [[ ! -f "${REPO_ROOT}/platform/gitops/${app_name}.yaml" ]]; then
    echo "ERROR: Missing GitOps manifest for ${app_name}. Did you run add-service.sh?"
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
for mock_name in "${MOCK_APPS_LIST[@]}"; do
  if [[ -d "${REPO_ROOT}/platform/charts/${mock_name}" ]]; then
    helm package "${REPO_ROOT}/platform/charts/${mock_name}" -d "${REPO_ROOT}/platform/charts" >/dev/null
  fi
done

if [[ -d "${REPO_ROOT}/platform/universal-chart" ]]; then
  helm package "${REPO_ROOT}/platform/universal-chart" -d "${REPO_ROOT}/platform/charts" >/dev/null
fi

if [[ -d "${REPO_ROOT}/platform/confluent-kafka-chart" ]]; then
  helm package "${REPO_ROOT}/platform/confluent-kafka-chart" -d "${REPO_ROOT}/platform/charts" >/dev/null
fi

helm repo index "${REPO_ROOT}/platform/charts"

echo "INFO: Starting local Helm repository server..."
docker stop deployguard-helm-server >/dev/null 2>&1 || true
docker run -d --rm --name deployguard-helm-server -p 8081:80 -v "${REPO_ROOT}/platform/charts:/usr/share/nginx/html" nginx:alpine >/dev/null

echo "INFO: Waiting for Helm repository server to be ready..."
wait_time=0
while ! curl -fsS http://127.0.0.1:8081/index.yaml >/dev/null 2>&1; do
  sleep 1
  wait_time=$((wait_time + 1))
  if [[ ${wait_time} -ge 15 ]]; then echo "ERROR: Helm server failed to start in time"; exit 1; fi
done

echo "INFO: Registering ArgoCD applications and secrets..."
kubectl apply -f "${REPO_ROOT}/platform/gitops/" >/dev/null

for app_name in "${SANITIZED_APPS[@]}" "${MOCK_APPS_LIST[@]}"; do
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
  # ... verification logic remains the same ...
  VERIFY_RELEASE_NAMES="${VERIFY_RELEASE_NAMES:-}"
  if [[ -z "${VERIFY_RELEASE_NAMES// }" ]]; then
    release_list=()
    for app_name in "${SANITIZED_APPS[@]}" "${MOCK_APPS_LIST[@]}"; do
      is_platform_app "${app_name}" || release_list+=("${app_name}")
    done
    if [[ ${#release_list[@]} -eq 0 ]]; then
      echo "ERROR: No service releases found for verification"
      exit 1
    fi
    VERIFY_RELEASE_NAMES="$(IFS=','; echo "${release_list[*]}")"
  fi

  RELEASE_NAMES="${VERIFY_RELEASE_NAMES}" \
  MOCK_APP_NAMES="${MOCK_APP_NAMES:-}" \
  HEALTH_PATH="${HEALTH_PATH:-/health}" \
  "${REPO_ROOT}/scripts/verify.sh"
fi