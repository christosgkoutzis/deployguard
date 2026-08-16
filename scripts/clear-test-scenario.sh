#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_DEPS="false"

for arg in "$@"; do
  if [[ "$arg" == "--skip-dependencies" ]]; then
    SKIP_DEPS="true"
  else
    echo "ERROR: Unknown argument '$arg'"
    echo "Usage: ./scripts/clear-test-scenario.sh [--skip-dependencies]"
    exit 1
  fi
done

echo "INFO: Cleaning user space (services, tests, mocks, seeds)..."
for target_dir in "services" "tests" "mocks" "seeds"; do
  if [[ -d "${REPO_ROOT}/${target_dir}" ]]; then
    find "${REPO_ROOT}/${target_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
done

if [[ "${SKIP_DEPS}" == "false" ]]; then
  echo "INFO: Cleaning platform dependencies..."
  if [[ -d "${REPO_ROOT}/platform/dependencies" ]]; then
    find "${REPO_ROOT}/platform/dependencies" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
else
  echo "INFO: Skipping platform dependencies cleanup."
fi

echo "INFO: Workspace cleared."
echo "INFO: Note: 'deployguard.yaml' was kept intentionally as a syntax reference."