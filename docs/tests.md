# Verification & Test Runner

DeployGuard verifies the selected environment and runs integration suites as Kubernetes Jobs on the cluster network.

## Test Archetype

Declare a service with `type: test`. Its default context is `tests/<name>/`, or supply `build_path`. Declare every prerequisite the suite needs, including workers and mocks.

```yaml
services:
  - name: integration-tests
    type: test
    build_path: ./test-suites/integration
    depends_on: [sample-api, queue-consumer, external-api-mock]
    env:
      - TARGET_URL=http://sample-api-service:80
    timeout: 600
```

Declare the referenced entities in the same topology. Sync registers a suspended Job without a readiness probe, Service, or Ingress. A successful deployment does not imply successful test execution.

Keep test data preparation inside the test program or its entry point. Test services do not support `init_command` or `INIT_COMMAND`; validation rejects these settings.

## Running Verification Checks

```bash
./scripts/deployguard verify
```

Verification reads `.local/state/inventory.json`, confirms the topology has not changed since sync, and checks the last selected entities. It waits for the requested ArgoCD revisions, healthy child Applications, completed platform seeds, Deployment rollout, and ingress health for web services and mocks. Dependency health covers the resources ArgoCD assesses, including PVCs. Workers need Deployment readiness without HTTP.

Sync verifies automatically; the separate command rechecks later. Retained unselected applications do not block the selected deployment; their own health status remains visible in ArgoCD. Selected deployment applications must reach the requested revision and pass their health checks. Test Job outcomes are checked by the test command and do not block deployment verification.

After a failed sync, correct the configuration or source and run sync again. DeployGuard coordinates pending ArgoCD work with the newly requested snapshot.

## Running Test Suites

For the bundled demo:

```bash
./scripts/deployguard list-tests
./scripts/deployguard sync --focus e2e-tests
./scripts/deployguard test e2e-tests
```

Each execution creates a new run ID in the generated snapshot. ArgoCD replaces the Job, and the runner waits for that Job's unique identity before following logs. Success requires `Complete=True` on that same Job. Failed Jobs, removed or replaced executions, and timeouts return nonzero status; Running pods and previously completed Jobs cannot satisfy it. Test Applications disable automatic sync retries and self-healing, and test Jobs use zero retries. Repeat the test command to rerun a suite, including after a failed execution. Sync alone registers suspended Jobs.

For your own suite, replace `e2e-tests` with its declared name. Tests must be selected in the last sync. The runner verifies that suite's prerequisites and reuses its deployed chart, configuration, and image. Other application revisions and test executions remain unchanged. Source or environment edits need another sync before execution.

## CI/CD Guardrails

The workflow runs on pull requests targeting master, pushes to master, and manual dispatch. It checks the demo and an independent custom topology on disposable Linux amd64 runners.

| Job | Coverage |
| --- | --- |
| `static-and-unit-tests` | Syntax, schema and topology validation, unit tests, and Helm rendering; includes isolation, locking, cleanup, lifecycle policies and configuration rules |
| `end-to-end-tests` | The demo's HTTP, database, messaging, cache, search and signed CSV download flows; Vault/ESO propagation, deployment selection, generated Git credential scans, and repeated sync/test execution |
| `deployment-lifecycle-tests` | An operator-free custom topology: paths, ports, environment and Secret handling, source and mock updates, seeds, focus retention/pruning, isolated Jobs, failures and recovery |
| `all-tests-passed` | Collects the other jobs' results and fails if any failed, was cancelled or was skipped; runs no tests itself |

End-to-end tests bootstrap one cluster, deploy and verify the focused environment, and run its suites and repeated sync/test checks. Only after those steps pass does the job expand to the full topology and repeat verification and tests. The full stage reuses the cluster and build cache. A focused-stage failure skips full expansion; failure diagnostics and cleanup still run.

Each functional job bootstraps its own cluster once. The demo includes Vault and ESO; the custom topology runs without them. Failure tests check the actual failed execution and subsequent recovery. Initialization failure checks require the new hook's expected exit code and a deployment error; unexpected results include Application operation diagnostics even when health appears successful. CI also checks that a changed Vault value reaches a restarted container, then restores it. Failed jobs collect cluster diagnostics before cleanup. `./scripts/deployguard assess` runs only in GitHub Actions.

Configure branch protection to require `all-tests-passed` if you want merges gated on the complete test workflow. A green run demonstrates this coverage on the tested toolchain and runner; it cannot prove every third-party chart, application, architecture, or host configuration works.

## Local Static Checks

After installation, run:

```bash
./scripts/deployguard check
```

The checker reads syntax/schema without importing applications, running services, or contacting a cluster. CI installs the assessment dependencies with `./scripts/deployguard install --assessment` and runs unit tests and offline Helm chart checks. See [Test Scenario](test-scenario.md) to deploy and verify the included demo.
