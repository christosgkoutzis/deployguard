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
wait_time=0
while true; do
  POD_NAME=$(kubectl -n deployguard get pod -l "app=${TEST_NAME}" --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -n 1 | tr -d '[:space:]')
  if [[ -n "$POD_NAME" ]]; then
    STATUS=$(kubectl -n deployguard get pod "$POD_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [[ "$STATUS" == "Running" || "$STATUS" == "Succeeded" || "$STATUS" == "Failed" ]]; then
      break
    fi
  fi
  sleep 2
  wait_time=$((wait_time + 2))
  if [[ ${wait_time} -ge 60 ]]; then
    echo "ERROR: Timeout waiting for pod to spawn."
    exit 1
  fi
done

echo "INFO: Streaming logs from ${POD_NAME}..."
kubectl -n deployguard logs -f "$POD_NAME" || true

echo "INFO: Waiting for job status to finalize..."
MAX_RETRIES=30
RETRY_COUNT=0

while [[ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]]; do
  JOB_COND=$(kubectl -n deployguard get job "${TEST_NAME}-workload" -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>/dev/null || echo "Unknown")

  if [[ "$JOB_COND" == *"Complete"* ]]; then
    echo "SUCCESS: Test suite passed!"
    exit 0
  elif [[ "$JOB_COND" == *"Failed"* ]]; then
    echo "ERROR: Test suite failed!"
    exit 1
  fi

  POD_PHASE=$(kubectl -n deployguard get pod "$POD_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
  if [[ "$POD_PHASE" == "Succeeded" ]]; then
    echo "SUCCESS: Test suite passed! (Pod Succeeded)"
    exit 0
  elif [[ "$POD_PHASE" == "Failed" ]]; then
    echo "ERROR: Test suite failed! (Pod Failed)"
    exit 1
  fi

  sleep 2
  RETRY_COUNT=$((RETRY_COUNT + 1))
done

echo "ERROR: Timeout waiting for Job/Pod to finalize its status!"
exit 1