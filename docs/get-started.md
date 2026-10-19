# Get Started

This guide walks you through installing tooling, bootstrapping a local cluster, defining a topology, and deploying it.

## Prerequisites

1. Docker with a running daemon, Git, Bash, curl, tar, and Python 3.11 or newer with venv/pip support.
2. Internet access for initial tool, chart, package, and image downloads.
3. Available ports for Kubernetes, HTTP ingress, and the generated Git source.
4. Enough Docker memory and disk for your topology. The full demo includes Elasticsearch, Kafka, and several databases; focus excludes unrelated tools but retains every declared prerequisite.

CI runs on Linux amd64. Tool installation supports Linux/macOS on amd64/arm64; upstream dependency images must also support your architecture. CI does not verify macOS or arm64 compatibility.

## 1. Prepare Python and Tooling

From the repository root:

```bash
./scripts/deployguard install
```

Install creates the local Python environment, installs the dependencies and pinned tools, and creates `.env` from `.env.example` when missing. Set your credentials and environment configuration in `.env` before continuing. Repeating install updates local dependencies and tools while preserving `.env` and cluster resources.

Use `./scripts/deployguard` for every command. It handles executable paths, temporary files, and caches inside `.local`; no shell activation or exports are needed. Installation does not change system-wide tools or shell settings. Python, Docker, Git, Bash, curl, and tar must already be available. Commands such as setup and sync require installation and do not install dependencies automatically.

Versions and Python dependencies are declared in `pyproject.toml`. To select a Python executable, use `DEPLOYGUARD_PYTHON=/path/to/python ./scripts/deployguard install`. Python 3.11 or newer is required.

## 2. Define and Validate Environment Topology

The built-in `deployguard.yaml` is a complete demo. A minimal topology looks like this:

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
| TIMEOUT_SECONDS | 600 | Default command wait timeout |

DeployGuard rejects conflicting Applications or bootstrap Secrets that it does not own. Use a separate checkout and cluster name for an independent environment.

## 4. Bootstrap Platform

```bash
./scripts/deployguard bootstrap
```

Bootstrap creates namespaces, installs the pinned ArgoCD chart, and creates the topology's AppProject. External Secrets Operator is installed only when the topology declares secret_stores. Bootstrap uses Helm; application workloads are subsequently reconciled by ArgoCD. ArgoCD’s internal Redis uses the official Docker Hub image, pinned by digest in `platform/config/argocd-values.yaml`.

## 5. Sync Environment

```bash
# Build and deploy the complete topology
./scripts/deployguard sync

# Select one entity and all its prerequisites
./scripts/deployguard sync --focus sample-api

# Explicitly remove unselected owned applications
./scripts/deployguard sync --focus sample-api --prune

# Recheck the last selected inventory
./scripts/deployguard verify
```

Sync builds the selected entities and verifies their deployment. Focus includes every prerequisite; unselected applications keep their deployed versions and do not block selected health checks. Add `--prune` to remove unselected applications and the resources they manage.

ArgoCD keeps managed resources matched to the deployed configuration. Manual changes made with kubectl or the Kubernetes dashboard can be overwritten; edit your source or topology and sync to make a lasting change. ArgoCD also deletes managed resources removed from an application's chart or configuration after sync. This happens without `--prune`; that flag controls removal of whole unselected applications.

Builds reuse Skaffold's cache. Service initialization runs on deployment syncs; platform seeds run when their inputs change. Tests run only through `./scripts/deployguard test <name>`. Run `./scripts/deployguard --help` to list commands.

## How It Works

1. **Cluster & Networking:** k3d runs k3s in Docker. Traefik exposes web services at `http://<name>.<CLUSTER_DOMAIN>:<INGRESS_PORT>`.
2. **Builds:** Skaffold builds selected application and seeder contexts. DeployGuard imports its reported image tags into the named k3d cluster.
3. **Local Git Source:** Each sync records generated charts and configuration in `.local/state/repository`. A Git commit identifies the exact version to deploy. Nginx serves this repository locally on SOURCE_PORT and inside the cluster at `http://deployguard-source-<cluster>/environment.git`. Your application repository is not committed or pushed.
4. **Deployment:** ArgoCD deploys the recorded configuration, waits for prerequisites to become healthy, and keeps managed resources matched to it.
5. **Local State:** Build results, inventory, generated Git snapshots, and an operation lock live under `.local/state`. The virtual environment, downloaded binaries, caches, installer staging files, and optional package build output also stay under `.local`, in separate subdirectories. A checkout manages one environment identity and cluster/namespace pairing. Use separate checkouts for independent environments.
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

## Next Steps

- [Explore the Test Scenario](test-scenario.md)
- [Configure Services](services.md)
- [Add Dependencies](dependencies.md)
- [Mock External APIs](mocks.md)
- [Run E2E Tests](tests.md)
- [Initialize Data](seeds.md)
