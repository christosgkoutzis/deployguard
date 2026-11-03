# Verify deployments and run tests

| Command | Purpose |
| --- | --- |
| `validate` | Check topology fields, files, references, and dependency order |
| `sync` | Build, deploy, initialize, and verify readiness |
| `verify` | Recheck the last selected deployment without rebuilding |
| `test <name>` | Run a test program as a Kubernetes Job and check its result |

Sync already verifies readiness. A healthy endpoint or running worker does not prove the application flow works; the integration suite checks that separately.

## Run the test scenario's suite

After [setup and bootstrap](get-started.md):

```bash
./scripts/deployguard list-tests
./scripts/deployguard sync --focus e2e-tests
./scripts/deployguard test e2e-tests
```

The suite checks backend and mock responses, greeting approval and cache reads, search indexing, and a signed CSV download. Success ends with `e2e-tests Job completed`. See the [test scenario](test-scenario.md) for the request flow.

## Use the existing suite as a reference

The suite lives in [tests/e2e-tests](../tests/e2e-tests). Its [Dockerfile](../tests/e2e-tests/Dockerfile) installs dependencies and starts pytest; [test_e2e.py](../tests/e2e-tests/test_e2e.py) contains the checks.

Its entry in [deployguard.yaml](../deployguard.yaml) uses `type: test`. `depends_on` includes the gateway, backend, workers, and mock; `env` supplies the gateway and storage addresses. Test programs handle their own data preparation. Validation rejects `init_command` and `INIT_COMMAND` on test services.

For another suite, supply its Dockerfile and test program, then declare its name and every prerequisite. Its default build path is `tests/<name>`; `build_path` can override it.

## Repeat tests and interpret results

Sync registers suspended test Jobs without executing them. A suite must be selected by the last sync before it can run.

Each `test` command verifies its prerequisites and starts a new execution. Success requires that same Job to complete. Failed, deleted, replaced, or timed-out executions return an error; a previous successful Job cannot satisfy a new run. Log streaming alone does not decide success.

Tests have zero retries, with ArgoCD automatic retries and self-healing disabled. Run `test` again to repeat a suite. Other test executions and application revisions remain unchanged.

After source, environment, or topology edits, sync before testing. Tests reuse deployed images. `verify` checks recorded configuration and readiness; it does not detect source edits. Retained, unselected applications do not block selected checks.

## What CI checks

The [workflow](../.github/workflows/cluster-integration.yml) runs on pull requests to master, pushes to master, and manual dispatch.

| Job | Purpose |
| --- | --- |
| `static-and-unit-tests` | Checks syntax and topology rules, runs unit tests, and renders Helm charts without a cluster. |
| `end-to-end-tests` | Deploys the test scenario and checks its application flows, Vault/ESO propagation, and repeated sync/test runs. |
| `deployment-lifecycle-tests` | Uses a separate sample environment to check updates, secrets, initialization, mocks, selection, pruning, test execution, and recovery. |
| `all-tests-passed` | Requires all three jobs to succeed; runs no additional tests. |

End-to-end tests create one cluster: the focused scenario must pass before the full scenario is deployed and tested on the same cluster. The lifecycle job uses its own cluster to check a topology without Vault or ESO.

Lifecycle checks deliberately introduce a crashing worker, an unavailable chart, failed initialization, a failed test, and an unknown focus name. Each command must fail as expected, then recovery must succeed. The scenario checks also change a Vault value, verify container propagation, and restore it. Both functional jobs collect failure diagnostics before cleanup.

CI covers Linux amd64 and the supplied environments, not every chart, application, or host. Require `all-tests-passed` in branch protection to gate merges on the full workflow.

## Check syntax locally

After installation:

```bash
./scripts/deployguard check
```

This reads code and schema syntax without starting applications or contacting a cluster. It does not check Markdown examples or run tests. CI separately runs unit tests and Helm rendering. `./scripts/deployguard assess` is reserved for GitHub Actions.
