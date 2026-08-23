#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
YAML_FILE="${REPO_ROOT}/deployguard.yaml"
FOCUS_SERVICE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topology) YAML_FILE="$2"; shift 2 ;;
    --focus) FOCUS_SERVICE="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument '$1'"; exit 1 ;;
  esac
done

export TOPOLOGY_FILE="${YAML_FILE}"

if [[ ! -f "$YAML_FILE" ]]; then
  echo "ERROR: Environment file $YAML_FILE not found!"
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "ERROR: 'yq' is required. Please run ./scripts/setup.sh first."
  exit 1
fi

echo "INFO: Syncing Environment from $YAML_FILE..."

if [[ -f "${REPO_ROOT}/.env" ]]; then
  echo "INFO: Securely loading secrets from .env..."
  set -a
  source "${REPO_ROOT}/.env"
  set +a
else
  echo "WARN: No .env file found! Make sure you provide one if your topology requires it."
fi

# Pre-process YAML to safely inject secrets into memory (not disk)
if command -v envsubst >/dev/null 2>&1; then
  PROCESSED_YAML=$(mktemp)
  envsubst < "$YAML_FILE" > "$PROCESSED_YAML"
  export TOPOLOGY_FILE="${PROCESSED_YAML}"
  YAML_FILE="${PROCESSED_YAML}"
fi

# Function to safely read lists from YAML
parse_list() {
  local query="$1"
  local result
  result=$(yq "$query" "$YAML_FILE" 2>/dev/null || true)
  if [[ "$result" == "null" || -z "$result" ]]; then
    echo ""
  else
    echo "$result"
  fi
}

SERVICES=$(parse_list '[.services[].name] | join(",")')
MOCKS=$(parse_list '.mocks | join(",")')
DEPS=$(parse_list '[.dependencies[].name] | join(",")')

# Apply Focus Graph Resolution (Full Recursive Tree)
if [[ -n "$FOCUS_SERVICE" ]]; then
  echo "INFO: Focus mode active. Resolving dependency tree for: $FOCUS_SERVICE"
  if ! echo "$SERVICES" | tr ',' '\n' | grep -qw "$FOCUS_SERVICE"; then
    echo "ERROR: Service '$FOCUS_SERVICE' not found in deployguard.yaml"
    exit 1
  fi

  RESOLVED_DEPS="$FOCUS_SERVICE"
  QUEUE="$FOCUS_SERVICE"
  
  # Recursively find all dependencies (services, platform apps, mocks)
  while [[ -n "$QUEUE" ]]; do
    CURRENT=$(echo "$QUEUE" | cut -d',' -f1)
    
    # Remove processed item from queue
    if [[ "$QUEUE" == *","* ]]; then
      QUEUE=$(echo "$QUEUE" | cut -d',' -f2-)
    else
      QUEUE=""
    fi
    
    CUR_DEPS=$(yq ".services[] | select(.name == \"$CURRENT\") | .depends_on | join(\",\")" "$YAML_FILE" 2>/dev/null || echo "")
    
    for d in $(echo "$CUR_DEPS" | tr ',' '\n'); do
      if [[ -n "$d" ]] && ! echo "$RESOLVED_DEPS" | tr ',' '\n' | grep -qw "$d"; then
        RESOLVED_DEPS="${RESOLVED_DEPS},${d}"
        if [[ -n "$QUEUE" ]]; then QUEUE="${QUEUE},${d}"; else QUEUE="${d}"; fi
      fi
    done
  done

  # Filter the original declarative lists based on the resolved tree
  FILTERED_SERVICES=""
  for s in $(echo "$SERVICES" | tr ',' '\n'); do
    if echo "$RESOLVED_DEPS" | tr ',' '\n' | grep -qw "$s"; then FILTERED_SERVICES="${FILTERED_SERVICES}${s},"; fi
  done
  SERVICES=$(echo "${FILTERED_SERVICES}" | sed 's/,$//')

  FILTERED_DEPS=""
  for d in $(echo "$DEPS" | tr ',' '\n'); do
    if echo "$RESOLVED_DEPS" | tr ',' '\n' | grep -qw "$d"; then FILTERED_DEPS="${FILTERED_DEPS}${d},"; fi
  done
  DEPS=$(echo "${FILTERED_DEPS}" | sed 's/,$//')

  FILTERED_MOCKS=""
  for m in $(echo "$MOCKS" | tr ',' '\n'); do
    if echo "$RESOLVED_DEPS" | tr ',' '\n' | grep -qw "$m"; then FILTERED_MOCKS="${FILTERED_MOCKS}${m},"; fi
  done
  MOCKS=$(echo "${FILTERED_MOCKS}" | sed 's/,$//')
fi

# 0. Clean stale local GitOps state
echo "INFO: === Cleaning up stale GitOps manifests ==="
find "${REPO_ROOT}/platform/gitops" -type f -name "*.yaml" -delete 2>/dev/null || true

# 1. Scaffold Services
echo "INFO: === Scaffolding Services ==="
for svc in $(echo "$SERVICES" | tr ',' '\n'); do
  if [[ -n "$svc" ]]; then
    "${REPO_ROOT}/scripts/add-service.sh" "$svc"
  fi
done

# 2. Scaffold Dependencies (Dynamic Resolution)
echo "INFO: === Scaffolding Dependencies ==="
for dep in $(echo "$DEPS" | tr ',' '\n'); do
  if [[ -z "$dep" ]]; then continue; fi
  
  NAME="$dep"
  REPO=$(yq ".dependencies[] | select(.name == \"$NAME\") | .repo" "$YAML_FILE")
  CHART=$(yq ".dependencies[] | select(.name == \"$NAME\") | .chart" "$YAML_FILE")
  VERSION=$(yq ".dependencies[] | select(.name == \"$NAME\") | .version" "$YAML_FILE")
  
  if [[ "$VERSION" == "null" || "$VERSION" == "" ]]; then
     helm repo add "temp-repo-$NAME" "$REPO" >/dev/null 2>&1 || true
     helm repo update "temp-repo-$NAME" >/dev/null 2>&1 || true
     VERSION=$(helm search repo "temp-repo-$NAME/$CHART" | awk 'NR==2 {print $2}')
     echo "INFO: Resolved dynamic version for $NAME: $VERSION"
  fi
  
  CMD=("${REPO_ROOT}/scripts/add-dependency.sh" "$NAME" "--repo" "$REPO" "--chart" "$CHART" "--version" "$VERSION")
  
  SECRET_NAME=$(yq ".dependencies[] | select(.name == \"$NAME\") | .secret.name" "$YAML_FILE")
  if [[ "$SECRET_NAME" != "null" ]]; then
    KV_LEN=$(yq ".dependencies[] | select(.name == \"$NAME\") | .secret.key_values | length" "$YAML_FILE")
    for k in $(seq 0 $((KV_LEN-1))); do
      KV=$(yq ".dependencies[] | select(.name == \"$NAME\") | .secret.key_values[$k]" "$YAML_FILE")
      CMD+=("--secret" "$SECRET_NAME" "$KV")
    done
  fi
  
  SET_LEN=$(yq ".dependencies[] | select(.name == \"$NAME\") | .set | length" "$YAML_FILE")
  if [[ "$SET_LEN" -gt 0 && "$SET_LEN" != "null" ]]; then
    for j in $(seq 0 $((SET_LEN-1))); do
      SET_VAL=$(yq ".dependencies[] | select(.name == \"$NAME\") | .set[$j]" "$YAML_FILE")
      CMD+=("--set" "$SET_VAL")
    done
  fi
  
  "${CMD[@]}"
done

# 3 Scaffold Platform Seeds (Dynamic ConfigMap)
echo "INFO: === Scaffolding Platform Seeds ==="
SEEDS_DIR="${REPO_ROOT}/seeds"
if [[ -d "${SEEDS_DIR}" ]] && [[ -n "$(ls -A "${SEEDS_DIR}" 2>/dev/null)" ]]; then
  echo "INFO: Found platform seeds. Generating dynamic ConfigMap chart..."
  SEED_CHART_DIR="${REPO_ROOT}/platform/charts/platform-seeds-chart"
  mkdir -p "${SEED_CHART_DIR}/templates"
  
  cat > "${SEED_CHART_DIR}/Chart.yaml" <<EOF
apiVersion: v2
name: platform-seeds-chart
version: 0.1.0
description: Dynamic platform seeds ConfigMap
type: application
EOF

  cat > "${SEED_CHART_DIR}/templates/configmap.yaml" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: deployguard-platform-seeds
data:
EOF

  for seed_file in "${SEEDS_DIR}"/*; do
    if [[ -f "${seed_file}" ]]; then
      echo "  $(basename "${seed_file}"): |" >> "${SEED_CHART_DIR}/templates/configmap.yaml"
      sed 's/^/    /' "${seed_file}" >> "${SEED_CHART_DIR}/templates/configmap.yaml"
      printf '\n' >> "${SEED_CHART_DIR}/templates/configmap.yaml"
    fi
  done

  # Create ArgoCD App for seeds
  cat > "${REPO_ROOT}/platform/gitops/platform-seeds.yaml" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-seeds
  namespace: argocd
spec:
  project: default
  source:
    repoURL: ${LOCAL_REGISTRY}
    chart: platform-seeds-chart
    targetRevision: 0.1.0
    helm:
      releaseName: platform-seeds
  destination:
    server: https://kubernetes.default.svc
    namespace: deployguard
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
EOF
fi

# 4. Trigger Deployment
echo "INFO: === Triggering Strict GitOps Deployment ==="

# Safely join the variables (remove redundant commas)
ALL_APPS=$(echo "${DEPS},${SERVICES},${MOCKS}" | sed 's/,,*/,/g' | sed 's/^,//' | sed 's/,$//')

if [[ -d "${SEEDS_DIR}" ]] && [[ -n "$(ls -A "${SEEDS_DIR}" 2>/dev/null)" ]]; then
  ALL_APPS="platform-seeds,${ALL_APPS}"
  DEPS="platform-seeds,${DEPS}"
fi

# Active Pruning: Delete ArgoCD apps that are no longer in focus to free up RAM
echo "INFO: === Pruning out-of-focus applications ==="
EXISTING_APPS=$(kubectl -n argocd get applications -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
for app in $EXISTING_APPS; do
  if ! echo "$ALL_APPS" | tr ',' '\n' | grep -qw "$app"; then
    echo "INFO: Deleting out-of-focus application: $app"
    kubectl -n argocd delete application "$app" --ignore-not-found >/dev/null
  fi
done

export EXTERNAL_DEPS="${DEPS}"
export MOCK_APP_NAMES="${MOCKS}"
export ARGO_APP_NAMES="${ALL_APPS}"
export SKIP_VERIFY="true"

"${REPO_ROOT}/scripts/dev-deploy.sh"
# Save the variables for the separate verify step of the CI
cat <<EOF > "${REPO_ROOT}/.sync-env.env"
export SERVICES="${SERVICES}"
export MOCKS="${MOCKS}"
export EXTERNAL_DEPS="${DEPS}"
export TOPOLOGY_FILE="${TOPOLOGY_FILE}"
EOF
echo "INFO: Environment synced successfully!"