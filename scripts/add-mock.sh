#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./scripts/add-mock.sh <mock-name>

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_NAME="${1:-}"

if [[ -z "${MOCK_NAME}" ]]; then
  echo "ERROR: Missing mock service name"
  echo "Usage: ./scripts/add-mock.sh <mock-name>"
  exit 1
fi

if [[ ! "${MOCK_NAME}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
  echo "ERROR: Mock name must be lowercase letters, numbers, and hyphens only"
  exit 1
fi

MOCK_DIR="${REPO_ROOT}/mocks/${MOCK_NAME}"

if [[ -d "${MOCK_DIR}" ]]; then
echo "ERROR: Mock directory already exists: mocks/${MOCK_NAME}"
  exit 1
fi

mkdir -p "${MOCK_DIR}"

cat > "${MOCK_DIR}/sample-endpoint.json" <<EOF
{
  "request": {
    "method": "GET",
    "url": "/api/sample"
  },
  "response": {
    "status": 200,
    "headers": {
      "Content-Type": "application/json"
    },
    "jsonBody": {
      "message": "Mock response from ${MOCK_NAME}"
    }
  }
}
EOF

echo "INFO: Created mock directory: mocks/${MOCK_NAME}"
echo "INFO: Edit the JSON files in this directory to define your HTTP mocks."