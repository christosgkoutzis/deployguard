# Verify deployments and run tests

These commands answer different questions:

| Command | Question | What it checks |
| --- | --- | --- |
| `validate` | Can DeployGuard read this configuration? | Topology fields, local files, references, and dependency order |
| `sync` | Can this environment be deployed? | Builds, deployment, initialization, and readiness |
| `verify` | Is the last selected deployment still ready? | Recorded configuration, requested ArgoCD revisions, dependency health, rollouts, and HTTP health endpoints |
| `test <name>` | Does the application behave as expected? | A test program's exit status, run as a Kubernetes Job |

Sync already verifies readiness. Use `verify` to recheck later without rebuilding. A running worker or a successful health endpoint does not prove that a message was processed; write integration tests for that behavior.

## Write a test for the sample API

First create the files from the [small API example](services.md#run-a-small-api).

Save `my-app/tests/checks.py`:

```python
import json
import os
from urllib.request import urlopen

with urlopen(os.environ["TARGET_URL"] + "/greeting", timeout=10) as response:
    body = json.load(response)
assert body["message"] == "Hello from sample-api", body
print("sample-api returned the expected greeting")
```

Save `my-app/tests/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY checks.py .
CMD ["python", "checks.py"]
```

Replace `my-app/deployguard.yaml` with this complete configuration:

```yaml
name: deployguard
services:
  - name: sample-api
    build_path: api
  - name: sample-tests
    type: test
    build_path: tests
    depends_on: [sample-api]
    env:
      - TARGET_URL=http://sample-api-service:80
    timeout: 600
```

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml --focus sample-tests
./scripts/deployguard test sample-tests --topology my-app/deployguard.yaml
```

The test prints `sample-api returned the expected greeting`. DeployGuard then reports `sample-tests Job completed`.

Keep test data preparation in the test program or its entry point. Validation rejects `init_command` and `INIT_COMMAND` on test services.

## Run and repeat tests

For the bundled demo, list and run its suite with:

```bash
./scripts/deployguard list-tests
./scripts/deployguard sync --focus e2e-tests
./scripts/deployguard test e2e-tests
```

Use `--topology my-app/deployguard.yaml` on each command for a custom topology.

Declare every prerequisite in `depends_on`, including workers and mocks. A suite must be selected by the last sync before it can run. Retained, unselected applications do not block its checks.

Sync registers test Jobs in a suspended state; it does not execute tests. Each `test` command verifies the suite's prerequisites, starts a new execution, follows its logs, and waits for that same Job to complete. Failed, deleted, replaced, or timed-out executions return an error. A previous successful Job cannot satisfy a new run.

Test Jobs use zero retries, and their ArgoCD Applications disable automatic retries and self-healing. Run `test` again to repeat a suite. Only that suite is replaced; other tests and application revisions remain unchanged. Job completion determines success; log streaming alone does not.

After source, environment, or topology edits, run `sync` before testing. The test command reuses deployed images and configuration. `verify` checks recorded topology configuration; it does not detect source edits or rebuild images.

## What CI checks

The workflow runs on pull requests to master, pushes to master, and manual dispatch.

| Job | Purpose |
| --- | --- |
| `static-and-unit-tests` | Checks syntax and topology rules, runs unit tests, and renders Helm charts without creating a cluster. |
| `end-to-end-tests` | Deploys the demo and tests its HTTP, database, Kafka, RabbitMQ, cache, search, Vault/ESO, and signed CSV flows. |
| `deployment-lifecycle-tests` | Uses a separate sample environment to test updates, secrets, initialization, mocks, selection, pruning, test execution, and failure recovery. |
| `all-tests-passed` | Fails unless all three test jobs succeed; it runs no additional tests. |

The end-to-end job creates one cluster. It first deploys and tests the focused environment, including repeated syncs and test runs. Only after that succeeds does it expand to the full demo on the same cluster, reusing the build cache. The lifecycle job needs a separate cluster to check a topology without Vault or ESO.

The lifecycle checks deliberately introduce failures: a crashing worker, an unavailable chart, a failed initialization command, a failed test, and an unknown focus name. Those commands must fail, and recovery must then succeed. The whole job passes only when those expectations are met.

The demo checks also change a Vault value, confirm that it reaches a restarted container, and restore it. Both functional jobs collect diagnostics on failure before deleting their runner resources.

CI runs on Linux amd64. A green run covers the supplied environments and tested toolchain; it cannot guarantee an arbitrary application, chart, host, or architecture. Require `all-tests-passed` in branch protection to gate merges on the full workflow.

## Check syntax locally

After installation:

```bash
./scripts/deployguard check
```

This reads code and schema syntax without starting applications or contacting a cluster. It does not validate Markdown examples or execute tests. CI separately installs assessment dependencies, runs the unit suite, and checks Helm rendering.

`./scripts/deployguard assess` is reserved for GitHub Actions. For normal use, follow [Get started](get-started.md) or the [demo walkthrough](test-scenario.md).
