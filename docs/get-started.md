# Get Started

This guide installs the local GitOps lab and runs an environment from a topology file: a YAML description of its services, dependencies, mocks, seeds, and tests. Commands below use the bundled demo to explore deployment and integration testing.

## Prerequisites

1. Docker with a running daemon, Git, Bash, curl, tar, and Python 3.11 or newer with venv/pip support.
2. Internet access for tool, chart, package, and image downloads. Local ingress names must resolve to localhost; the default domain uses `nip.io`.
3. Available ports for Kubernetes, HTTP ingress, and the generated Git source.
4. Enough Docker memory and disk for your topology. The full demo includes Elasticsearch, Kafka, and several databases; focus excludes unrelated tools but retains every declared prerequisite.

CI runs on Linux amd64. Tool installation supports Linux/macOS on amd64/arm64; upstream dependency images must also support your architecture. CI does not verify macOS or arm64 compatibility.

## 1. Prepare Python and Tooling

From the repository root:

```bash
./scripts/deployguard install
```

Install creates the local Python environment, installs the dependencies and pinned tools, and creates `.env` from `.env.example` when missing. Set your credentials and environment configuration in `.env` before continuing. Repeating install updates local dependencies and tools while preserving `.env` and cluster resources.

The example credentials belong to the local demo dependencies. No AWS account or external Vault service is required.

Use `./scripts/deployguard` for every command. It handles executable paths, temporary files, and caches inside `.local`; no shell activation or exports are needed. Installation does not change system-wide tools or shell settings. Python, Docker, Git, Bash, curl, and tar must already be available. Commands such as setup and sync require installation and do not install dependencies automatically.

Versions and Python dependencies are declared in `pyproject.toml`. To select a Python executable, use `DEPLOYGUARD_PYTHON=/path/to/python ./scripts/deployguard install`. Python 3.11 or newer is required.

## 2. Define and Validate Environment Topology

For the bundled demo, leave `deployguard.yaml` unchanged and continue with validation below. To run your own application, prepare its build context, configuration, dependencies, and test data using the [service requirements](services.md). Declare each required process as a service or worker and describe its prerequisites explicitly; DeployGuard does not import Compose files or process definitions.

Replace `deployguard.yaml` or choose another topology with `--topology`. The following example requires your own source folder and Dockerfile:

```yaml
apiVersion: deployguard/v1
name: my-local-env
services:
  - name: sample-api
    build_path: ./apps/sample-api
    port: 3000
    health_endpoint: /ready
    env:
      - APP_MODE=development
```

The build context must contain a Dockerfile. The application must listen on `0.0.0.0:3000` and return a successful response at `/ready`.

```bash
./scripts/deployguard validate
./scripts/deployguard doctor
```

Validation reads configuration and files without building or contacting Kubernetes. It rejects unknown fields, duplicate entities, missing prerequisites, dependency cycles, missing build contexts, invalid mappings, and invalid secret references. The format is defined by `platform/config/topology.schema.json`. The optional apiVersion defaults to deployguard/v1; name defaults to deployguard.

Use `--topology path/to/topology.yaml` or `TOPOLOGY_FILE` to choose another topology. Build paths, chart paths, seed directories, and mock locations resolve relative to that file's directory. A service's env_file resolves inside its build context.

## 3. Create the Local Cluster

```bash
./scripts/deployguard setup
```

This creates a pinned k3s cluster with one server and two agents. An existing cluster with the configured name is retained. Kubernetes and Helm commands target `k3d-${CLUSTER_NAME}` explicitly, and creation does not switch the current kubectl context.

Configuration comes from the repository .env, with process environment variables taking precedence:

| Setting | Default | Purpose |
| --- | --- | --- |
| CLUSTER_NAME | control-plane-cluster | k3d cluster identity |
| NAMESPACE | deployguard | Application namespace |
| ARGO_APP_NAMESPACE | argocd | ArgoCD and Application namespace |
| CLUSTER_DOMAIN | 127.0.0.1.nip.io | Ingress hostname suffix |
| API_PORT | 6443 | Kubernetes API on localhost |
| INGRESS_PORT | 8080 | HTTP ingress on localhost |
| SOURCE_PORT | 8081 | Generated Git source on localhost |
| TIMEOUT_SECONDS | 600 | Default timeout for each readiness or initialization wait |

DeployGuard rejects conflicting Applications or bootstrap Secrets that it does not own. Use a separate checkout and cluster name for an independent environment.

## 4. Bootstrap Platform

```bash
./scripts/deployguard bootstrap
```

Bootstrap creates namespaces, installs the pinned ArgoCD chart, and creates the topology's AppProject. External Secrets Operator is installed only when the topology declares secret_stores. Bootstrap uses Helm; application workloads are subsequently reconciled by ArgoCD. ArgoCD’s internal Redis uses the official Docker Hub image, pinned by digest in `platform/config/argocd-values.yaml`.

## 5. Deploy and Test

```bash
./scripts/deployguard sync
./scripts/deployguard test e2e-tests
```

Sync builds and verifies the complete environment. The test command then runs the bundled integration suite. Deployment verification alone does not test application request flows. For your own topology, use its declared test name.

Use `./scripts/deployguard verify` later to recheck deployment health without rebuilding. Source changes require another sync; DeployGuard does not watch files or synchronize edits into running containers.

### Selecting Part of the Environment

Focus selects one entity and every prerequisite. For the demo test suite:

```bash
./scripts/deployguard sync --focus e2e-tests
```

For your own topology, replace `e2e-tests` with the entity you want to select. Unselected applications keep their deployed versions and do not block selected health checks.

To also remove unselected applications and the resources they manage, explicitly request pruning:

```bash
./scripts/deployguard sync --focus e2e-tests --prune
```

ArgoCD keeps deployment resources matched to the deployed configuration. Manual changes made with kubectl or the Kubernetes dashboard can be overwritten; edit your source or topology and sync to make a lasting change. Test Applications synchronize requested revisions with automatic retries and self-healing disabled; use the test command to start another execution. ArgoCD also deletes managed resources removed from an application's chart or configuration after sync. This happens without `--prune`; that flag controls removal of whole unselected applications.

Builds reuse Skaffold's cache. Service initialization runs on deployment syncs; platform seeds run when their inputs change. Tests run only through `./scripts/deployguard test <name>`. Run `./scripts/deployguard --help` to list commands.

## How It Works

1. **Cluster & Networking:** k3d runs k3s in Docker. Traefik exposes web services at `http://<name>.<CLUSTER_DOMAIN>:<INGRESS_PORT>`.
2. **Builds:** Skaffold builds selected application and seeder contexts. DeployGuard imports its reported image tags into the named k3d cluster.
3. **Local Git Source:** Each sync records generated charts and configuration in `.local/state/repository`. A Git commit identifies the exact version to deploy. Nginx serves this repository locally on SOURCE_PORT and inside the cluster at `http://deployguard-source-<cluster>/environment.git`. Your application repository is not committed or pushed.
4. **Deployment:** Each declared entity becomes an ArgoCD Application, which tracks its configuration and health. ArgoCD deploys the recorded snapshot in dependency order. Deployment resources are continuously reconciled; test executions follow the explicit test command.
5. **Local State:** `.local` contains the installed tools, caches, generated Git snapshots, and deployment inventory. Each checkout manages one environment and cluster/namespace pairing. Use separate checkouts for independent environments.
6. **Secrets:** DeployGuard supplies declared credentials directly to Kubernetes Secrets. Generated configuration names those Secrets instead of containing their values. Vault and External Secrets Operator (ESO) are optional integrations. Keep credentials out of chart files, seed scripts, and mock mappings too.

## Repository Layout

```text
README.md                 Overview and workflow
deployguard.yaml          Your local environment topology
.env.example              Local configuration example
pyproject.toml            Tool dependencies, extras, command and version pins
scripts/deployguard       Command entry point and local installation
scripts/core/             DeployGuard command implementation
platform/charts/          Reusable workload charts
platform/dependencies/    Local infrastructure charts
platform/config/          Topology schema and ArgoCD settings
services/                 Demo applications
mocks/                    Demo mappings
seeds/<name>/             Seed script and its runtime files
tests/unit/               CI unit and chart checks
tests/e2e-tests/           Demo integration suite
tests/platform-fixture/   CI sample topology and applications
docs/                     User guides
.github/workflows/        CI assessment
.local/                   Ignored generated content only
```

The single entry point is `./scripts/deployguard`: install, setup, bootstrap, sync, verify, test, validate, doctor, list-tests, clear-scenario, check, and runner-only assess.

## Inspecting Failures

Reconciliation failures report the requested revision and ArgoCD Application status. Inspect the selected cluster with the installed kubectl:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get applications
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get pods
```

Use your configured context and namespaces when they differ. After correcting the configuration or source, rerun sync. See [the demo inspection commands](test-scenario.md#inspecting-the-local-environment) for logs, events, and dependency access.

## Next Steps

- [Explore the Test Scenario](test-scenario.md)
- [Configure Services](services.md)
- [Add Dependencies](dependencies.md)
- [Mock External APIs](mocks.md)
- [Run E2E Tests](tests.md)
- [Initialize Data](seeds.md)
