# Verification & Test Runner

DeployGuard includes a built-in test runner that executes your integration and end-to-end (E2E) tests directly inside the cluster, ensuring 100% realistic internal networking.

## Test Archetype

Tests are treated as a first-class entity in DeployGuard. By defining a workload with `type: test` in your topology YAML, the platform creates an ephemeral Kubernetes `Job` instead of a continuous `Deployment`.

**Example `deployguard.yaml` configuration:**
```yaml
services:
  - name: e2e-tests
    type: test
    depends_on:
      - ruby-gateway
      - python-backend
    env:
      - TARGET_URL="http://ruby-gateway-service:80"
```

Because it is a `test` type, DeployGuard knows not to expect a health endpoint or an exposed K8s Service/Ingress.

## Running Verification Checks

After syncing an environment, you can run automated verification to ensure all workloads are completely rolled out, PVCs are bound, and HTTP health endpoints are returning successful responses. 

Because the environment is fully dynamic, you run verification by sourcing the topology output variables generated during the sync:

```bash
source .sync-env.env
MOCK_APP_NAMES="${MOCKS}" \
./scripts/verify.sh
```

## Running the E2E Test Suite

To spawn the test Job, stream its logs to your terminal, and automatically evaluate its exit status, run:

```bash
./scripts/run-tests.sh <test-service-name>

# Example:
./scripts/run-tests.sh e2e-tests
```

This script will automatically wait for the pod to initialize, stream the test execution logs in real-time, and exit with `0` on success or `1` on failure by reading the official Kubernetes Job conditions.

## CI/CD Guardrails

DeployGuard includes a GitHub Actions workflow (`.github/workflows/cluster-integration.yml`). On every push to the master branch or pull request, it runs a full **End-to-End Cluster Validation**. 

It dynamically spins up an ephemeral k3d cluster, bootstraps ArgoCD, applies the `deployguard.yaml` topology, and runs the entire `sync-env`, `verify`, and `run-tests` flow dynamically based on your YAML definitions. 

A safe, minimal debug step is also included. If the CI pipeline encounters an error, this step automatically fetches events and logs **only** for the specific pods that are failing or stuck in a pending state, preventing log bloat while providing exact clues to fix the build.