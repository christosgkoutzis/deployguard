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

## Running Verification Checks

```bash
./scripts/deployguard verify
```

Verification reads `.local/state/inventory.json`, confirms the topology has not changed since sync, and checks the last selected entities. It waits for the requested ArgoCD revisions, healthy child Applications, completed platform seeds, Deployment rollout, and ingress health for web services and mocks. Dependency health covers the resources ArgoCD assesses, including PVCs. Workers need Deployment readiness without HTTP.

Sync verifies automatically; the separate command rechecks later. Retained unselected applications do not block verification or the parent Application's sync waves; their own health status remains visible in ArgoCD. Selected applications must reach the requested revision and pass their health checks. Test Job outcomes are checked by the test command and do not block deployment verification.

Sync publishes a snapshot for ArgoCD to reconcile automatically. If the parent Application is still synchronizing an older revision, DeployGuard requests its termination through ArgoCD before waiting for the requested snapshot. This lets a focused sync proceed after an unrelated application fails.

## Running Test Suites

```bash
./scripts/deployguard list-tests
./scripts/deployguard sync --focus e2e-tests
./scripts/deployguard test e2e-tests
```

Each execution creates a new run ID in the generated snapshot. ArgoCD replaces the Job, and the runner waits for that execution before following logs. Success requires `Complete=True` on the Kubernetes Job. Failed Jobs and timeouts return nonzero status; Running pods and previously completed Jobs cannot satisfy it. Repeat the test command to rerun a suite, including after a failed execution. Sync alone registers suspended Jobs.

Test names must be declared and selected in the last sync. The runner verifies that suite's prerequisites and reuses its deployed chart, configuration, and image. Other application revisions and test executions remain unchanged. Source or environment edits need another sync before execution.

## CI/CD Guardrails

The workflow runs on pull requests targeting master, pushes to master, and manual dispatch. Jobs are named for the behavior they verify:

Each test job uses a separate runner. The "Check out repository" step fetches the source with GitHub's checkout action; "Prepare Python" selects the required Python interpreter with GitHub's setup-python action. Action references and tool versions remain explicit so the workflow uses a known configuration.

| Job | Coverage |
| --- | --- |
| `static-and-unit-tests` | Python/shell/JSON/YAML syntax, schema validity, unit tests, offline Helm rendering, demo and fixture topology validation; runs once |
| `end-to-end-tests` | The included services' HTTP, database, messaging, cache, search and CSV export flows, including signed downloads and rejection of unsigned downloads; one bootstrap, focused deployment followed by full expansion on the same cluster, deployment health, build and Application inventory, generated Git credential scan, repeated sync and tests |
| `deployment-lifecycle-tests` | Custom paths/ports/health/env files, optional Vault, Secret references, workers without HTTP, seeds, mocks, repeated Jobs, changed source updating images, focus retention/pruning, failing initialization, missing charts, failed-test retries, unhealthy retained apps, Secret updates, mapping updates, isolated test execution |
| `all-tests-passed` | Collects the other jobs' results and fails if any failed, was cancelled or was skipped; runs no tests itself |

End-to-end tests bootstrap one cluster, deploy and verify the focused environment, and run its suites and repeated sync/test checks. Only after those steps pass does the job expand to the full topology and repeat verification and tests. The full stage reuses the cluster and build cache. A focused-stage failure skips full expansion; failure diagnostics and cleanup still run.

Each functional job bootstraps its own cluster once. The E2E job covers the demo with Vault and ESO; the lifecycle job covers an independent application without them. Sync includes verification, so the workflow does not immediately run verification again. The lifecycle assessment owns its repeated test executions; the workflow does not repeat them beforehand. Repeated syncs and test executions exercise idempotency and new Job creation.

The initialization-failure assessment observes new hook pods while sync runs and requires exit code 37 and an explicit initialization or ArgoCD sync failure. It uses the configured command wait to allow ArgoCD's retries to finish. A timeout or a failure from a previous pod cannot satisfy it.

The generic fixture tests custom application layouts alongside the demo. Its source files are maintained CI inputs; assessment changes use a temporary copy under ignored `.local/tmp`, removed when the assessment ends. All jobs use disposable Linux amd64 runners; functional jobs clean up their own resources. Failure diagnostics collect unready pod descriptions, bounded logs, warning events, and Application status. `./scripts/deployguard assess` refuses local execution outside GitHub Actions.

Sync reports snapshot generation, each selected entity, Git recording, source startup and Application submission. Unexpected file or data errors report their exception type and DeployGuard source location; filesystem errors include an error number and invalid JSON includes its line and column. Raw exception messages, file contents and configuration values are omitted.

The local Git source has a 30-second HTTP readiness deadline. Connection resets or disconnects during startup are retried; sync fails if the source remains unavailable when the deadline expires.

A failed child-Application or initialization wait reports the requested, desired and observed revisions, sync and health status, condition messages, operation phase and resource results. Messages redact declared credential values; manifests and Secret contents are omitted. CI diagnostics also report node readiness and reconciliation details for Applications that are unhealthy or out of sync.

Configure branch protection to require `all-tests-passed` if you want merges gated on the complete test workflow. A green run demonstrates this coverage on the tested toolchain and runner; it cannot prove every third-party chart, application, architecture, or host configuration works.

## Local Static Checks

After installation, run:

```bash
./scripts/deployguard check
```

The checker reads syntax/schema without importing applications, running services, or contacting a cluster. CI installs the assessment dependencies with `./scripts/deployguard install --assessment` and runs unit tests and offline Helm chart checks. See [Test Scenario](test-scenario.md) to deploy and verify the included demo.
