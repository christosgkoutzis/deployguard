#!/usr/bin/env bash
set -euo pipefail

TEST_NAME="${1:-}"

if [[ -z "${TEST_NAME}" ]]; then
  echo "ERROR: Usage: ./scripts/run-tests.sh <test-service-name>"
  exit 1
fi

echo "INFO: Triggering E2E Test Suite: ${TEST_NAME}"
echo "INFO: Deleting previous test job (if any)..."
kubectl -n deployguard delete job "${TEST_NAME}-workload" --ignore-not-found >/dev/null

echo "INFO: Syncing ArgoCD Application to spawn new test job..."
kubectl -n argocd patch application "${TEST_NAME}" \
  --type merge \
  -p '{"operation":{"sync":{"prune":true}}}' >/dev/null

echo "INFO: Waiting for pod to initialize..."
while true; do
  POD_NAME=$(kubectl -n deployguard get pod -l "app=${TEST_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -n 1)
  if [[ -n "$POD_NAME" ]]; then
    STATUS=$(kubectl -n deployguard get pod "$POD_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [[ "$STATUS" == "Running" || "$STATUS" == "Succeeded" || "$STATUS" == "Failed" ]]; then
      break
    fi
  fi
  sleep 1
done

echo "INFO: Streaming logs from ${POD_NAME}..."
kubectl -n deployguard logs -f "$POD_NAME"

echo "INFO: Waiting for pod status to finalize..."
while true; do
  PHASE=$(kubectl -n deployguard get pod "$POD_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
  
  if [[ "$PHASE" == "Succeeded" ]]; then
    echo "SUCCESS: Test suite passed!"
    exit 0
  elif [[ "$PHASE" == "Failed" ]]; then
    echo "ERROR: Test suite failed!"
    exit 1
  fi
  
  sleep 1
done