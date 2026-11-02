# Get started

This guide runs the bundled demo. Keep `deployguard.yaml` unchanged for this walkthrough.

## Before you start

You need:

- Docker with a running daemon.
- Git, Bash, curl, tar, and Python 3.11 or newer with venv and pip support.
- Internet access to download tools, charts, packages, and images.
- Free localhost ports 6443, 8080, and 8081.
- Docker memory and disk for the selected services. The full demo runs Elasticsearch, Kafka, several databases, and their management tools. Resource needs depend on the selected images and their configuration.

The installer supports Linux and macOS on amd64 and arm64. CI tests Linux amd64; macOS and arm64 are not covered, and dependency images must support your architecture.

The default hostnames use `nip.io` to resolve to `127.0.0.1`. Your DNS configuration must allow those lookups.

## 1. Install

Run commands from the repository root:

```bash
./scripts/deployguard install
```

This installs Python dependencies and pinned tools under `.local` and creates `.env` from `.env.example` if needed. It preserves an existing `.env`, system tools, and shell settings. Repeating install refreshes the checkout's dependencies and tools.

Review `.env` in your editor. Its credentials are for local dependencies: no AWS account or external Vault service is needed. Choose your local passwords before deploying.

```bash
./scripts/deployguard validate
./scripts/deployguard doctor
```

`validate` checks the topology and referenced local files. `doctor` checks that required executables are available and prints the configured tool versions. It does not test Docker daemon health or available memory.

Use `./scripts/deployguard` for application commands; it finds the checkout's tools without shell activation or exports. To choose a Python interpreter during installation, set `DEPLOYGUARD_PYTHON` to its executable path.

## 2. Create and bootstrap the cluster

```bash
./scripts/deployguard setup
./scripts/deployguard bootstrap
```

`setup` creates a k3s cluster in Docker through k3d, with one server and two agents. An existing cluster with the configured name is retained. The command does not switch your current kubectl context.

`bootstrap` installs ArgoCD, which applies the generated Kubernetes configuration. It also installs External Secrets Operator when the topology declares Vault stores.

## 3. Deploy and test

```bash
./scripts/deployguard sync
./scripts/deployguard test e2e-tests
```

`sync` builds the application images, loads them into k3d, deploys the topology, runs initialization, and waits for readiness. A successful sync ends with `Environment synced and verified`.

`test` then runs the demo's four integration checks. It verifies HTTP responses, event processing, cache reads, search results, and a signed CSV download. Success ends with `e2e-tests Job completed`.

Open [the gateway](http://ruby-gateway.127.0.0.1.nip.io:8080/) and follow the [demo walkthrough](test-scenario.md). The gateway's CSV download URL is internal to the cluster; that guide includes a command to retrieve the file.

## 4. Change code and deploy again

After editing a service, run:

```bash
./scripts/deployguard sync
./scripts/deployguard test e2e-tests
```

Builds reuse Skaffold's cache. DeployGuard does not watch files or copy edits into running containers.

To check deployment readiness later without rebuilding:

```bash
./scripts/deployguard verify
```

Readiness is separate from application testing. A worker can be running without successfully processing messages; the integration suite checks that behavior.

## Deploy only a service or test and its prerequisites

For the demo test suite:

```bash
./scripts/deployguard sync --focus e2e-tests
./scripts/deployguard test e2e-tests
```

On a fresh cluster this excludes Dozzle and Kafbat UI, while retaining all dependencies needed by the test. On an existing cluster, unselected applications remain at their deployed versions and do not block the selected checks.

To remove unselected applications and their managed resources as well:

```bash
./scripts/deployguard sync --focus e2e-tests --prune
```

ArgoCD also removes resources deleted from a selected application's chart. That is separate from `--prune`, which removes whole unselected applications. Manual changes to managed resources can be overwritten; edit the source or topology and sync to keep a change.

## Configuration

Settings come from the repository's `.env`. Process environment variables override them.

| Setting | Default | Purpose |
| --- | --- | --- |
| CLUSTER_NAME | control-plane-cluster | k3d cluster name |
| NAMESPACE | deployguard | Namespace for application resources |
| ARGO_APP_NAMESPACE | argocd | Namespace for ArgoCD and its Application objects |
| CLUSTER_DOMAIN | 127.0.0.1.nip.io | Suffix for application hostnames |
| API_PORT | 6443 | Kubernetes API port on localhost |
| INGRESS_PORT | 8080 | HTTP ingress port on localhost |
| SOURCE_PORT | 8081 | Local Git server port on localhost |
| TIMEOUT_SECONDS | 600 | Default wait for each readiness or initialization check |

Use your configured domain and port in place of the default URLs throughout these guides. Each checkout manages one environment. A separate checkout, cluster name, and free ports are needed for an independent environment.

## How deployment works

1. Skaffold builds selected Docker contexts. k3d imports the images into the local cluster.
2. DeployGuard writes charts and configuration to a separate Git repository under `.local/state/repository`. Nginx makes it available to ArgoCD. Your application repository is not committed or pushed.
3. Each declared service, dependency, mock, or seed becomes an ArgoCD Application: an object telling ArgoCD what configuration to deploy and monitor.
4. ArgoCD applies the snapshot in dependency order and keeps resources matched to it.
5. DeployGuard supplies declared Kubernetes Secrets directly. Vault and External Secrets Operator are optional.
6. Tools, caches, snapshots, and the last deployment inventory stay under `.local`.

Application initialization runs on deployment syncs. Shared seeds run when their inputs change. Tests run through the test command. See [initialization](seeds.md) and [tests](tests.md) for details.

## Use your own application

Start with the [complete API example](services.md#run-a-small-api). It uses `my-app/deployguard.yaml`, leaving the bundled topology intact.

Use `--topology my-app/deployguard.yaml` on each command for that example. Paths inside the topology are relative to its directory; a service's `env_file` is relative to its build context. `TOPOLOGY_FILE` can also select a topology.

The topology schema is `platform/config/topology.schema.json`. `apiVersion` is optional and defaults to `deployguard/v1`; `name` defaults to `deployguard`. Validation rejects unknown fields, missing references, and dependency cycles.

## Inspect a failure

These commands use the tools installed by DeployGuard and target the default cluster:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get applications
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get pods
```

Read the failing application's diagnostics and pod status. For example, `OOMKilled` indicates an out-of-memory termination; a larger wait will not resolve a container repeatedly running out of memory. After correcting source or configuration, sync again.

More [inspection commands](test-scenario.md#inspect-the-environment) are available in the demo guide.

## Repository layout

| Path | Contents |
| --- | --- |
| `deployguard.yaml` | Bundled demo topology; use another topology for your own environment |
| `.env.example` | Example host settings and local credentials |
| `pyproject.toml` | Python dependencies and tool version pins |
| `scripts/deployguard` | Command entry point |
| `scripts/core/` | Command implementation |
| `platform/charts/` | Shared charts for applications, mocks, seeds, and tests |
| `platform/dependencies/` | Local Kafka and RabbitMQ charts |
| `platform/config/` | Topology schema and ArgoCD settings |
| `services/`, `mocks/`, `seeds/` | Bundled demo inputs |
| `tests/e2e-tests/` | Demo integration suite |
| `tests/platform-fixture/` | Separate environment used by CI lifecycle tests |
| `tests/unit/` | Unit and chart checks |
| `.github/workflows/` | CI workflow |
| `.local/` | Ignored tools and generated state |

Next: [run your own services](services.md), [add dependencies](dependencies.md), or [understand CI](tests.md#what-ci-checks).
