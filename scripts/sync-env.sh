#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! python3 -c "import yaml" 2>/dev/null; then
  echo "INFO: Installing pyyaml safely..."
  python3 -m pip install pyyaml --break-system-packages >/dev/null 2>&1 || python3 -m pip install pyyaml --user >/dev/null 2>&1 || true
fi

echo "INFO: Running python orchestrator..."
python3 "${REPO_ROOT}/scripts/sync.py" "$@"

echo "INFO: Triggering dev-deploy..."
"${REPO_ROOT}/scripts/dev-deploy.sh"

echo "INFO: Sync complete!"
