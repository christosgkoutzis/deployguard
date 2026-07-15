#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
YAML_FILE="${REPO_ROOT}/deployguard.yaml"

if [[ ! -f "$YAML_FILE" ]]; then
  echo "ERROR: Environment file $YAML_FILE not found!"
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "ERROR: 'yq' is required. Please run ./scripts/setup.sh first."
  exit 1
fi

echo "INFO: Syncing Environment from $YAML_FILE..."


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

SERVICES=$(parse_list '.services | join(",")')
MOCKS=$(parse_list '.mocks | join(",")')
PLATFORM=$(parse_list '.platform_apps | join(",")')
DEPS=$(parse_list '[.dependencies[].name] | join(",")')

# 1. Scaffold Services
echo "INFO: === Scaffolding Services ==="
for svc in $(parse_list '.services[]'); do
  "${REPO_ROOT}/scripts/add-service.sh" "$svc"
done

# 2. Scaffold Dependencies (με Dynamic Resolution)
echo "INFO: === Scaffolding Dependencies ==="
DEPS_LEN=$(yq '.dependencies | length' "$YAML_FILE" 2>/dev/null || echo 0)
if [[ "$DEPS_LEN" =~ ^[0-9]+$ ]] && [[ "$DEPS_LEN" -gt 0 ]]; then
  for i in $(seq 0 $((DEPS_LEN-1))); do
    NAME=$(yq ".dependencies[$i].name" "$YAML_FILE")
    REPO=$(yq ".dependencies[$i].repo" "$YAML_FILE")
    CHART=$(yq ".dependencies[$i].chart" "$YAML_FILE")
    VERSION=$(yq ".dependencies[$i].version" "$YAML_FILE")

    # Dynamic Version Resolution if version is null or empty
    if [[ "$VERSION" == "null" || "$VERSION" == "" ]]; then
       helm repo add "temp-repo-$NAME" "$REPO" >/dev/null 2>&1 || true
       helm repo update "temp-repo-$NAME" >/dev/null 2>&1 || true
       VERSION=$(helm search repo "temp-repo-$NAME/$CHART" | awk 'NR==2 {print $2}')
       echo "INFO: Resolved dynamic version for $NAME: $VERSION"
    fi

    CMD=("${REPO_ROOT}/scripts/add-dependency.sh" "$NAME" "--repo" "$REPO" "--chart" "$CHART" "--version" "$VERSION")

    SECRET_NAME=$(yq ".dependencies[$i].secret.name" "$YAML_FILE")
    if [[ "$SECRET_NAME" != "null" ]]; then
      KV_LEN=$(yq ".dependencies[$i].secret.key_values | length" "$YAML_FILE")
      for k in $(seq 0 $((KV_LEN-1))); do
        KV=$(yq ".dependencies[$i].secret.key_values[$k]" "$YAML_FILE")
        CMD+=("--secret" "$SECRET_NAME" "$KV")
      done
    fi

    SET_LEN=$(yq ".dependencies[$i].set | length" "$YAML_FILE")
    if [[ "$SET_LEN" -gt 0 && "$SET_LEN" != "null" ]]; then
      for j in $(seq 0 $((SET_LEN-1))); do
        SET_VAL=$(yq ".dependencies[$i].set[$j]" "$YAML_FILE")
        CMD+=("--set" "$SET_VAL")
      done
    fi

    "${CMD[@]}"
  done
fi

# 3. Trigger Deployment
echo "INFO: === Triggering Strict GitOps Deployment ==="

# Safely join the variables (remove redundant commas)
ALL_APPS=$(echo "${DEPS},${SERVICES},${PLATFORM}" | sed 's/,,*/,/g' | sed 's/^,//' | sed 's/,$//')
PLATFORM_APPS_COMBINED=$(echo "${PLATFORM},${DEPS}" | sed 's/,,*/,/g' | sed 's/^,//' | sed 's/,$//')

export PLATFORM_APPS="${PLATFORM_APPS_COMBINED}"
export MOCK_APP_NAMES="${MOCKS}"
export ARGO_APP_NAMES="${ALL_APPS}"
export SKIP_VERIFY="true"

"${REPO_ROOT}/scripts/dev-deploy.sh"

# Save the variables for the separate verify step of the CI
cat <<EOF > "${REPO_ROOT}/.sync-env.env"
export SERVICES="${SERVICES}"
export MOCKS="${MOCKS}"
export PLATFORM_APPS_COMBINED="${PLATFORM_APPS_COMBINED}"
EOF
echo "INFO: Environment synced successfully!"