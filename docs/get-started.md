# Get Started

This guide walks you through bootstrapping DeployGuard from scratch, defining a minimal service topology, and executing a deployment.

## Prerequisites

1. Docker daemon running locally.
2. Internet access for image/chart downloads.
3. Shell access with permissions to run the scripts.

## 1. Create Local Cluster and Tooling

```bash
./scripts/setup.sh
```

Installs missing tools (`kubectl`, `k3d`, `helm`, `yq`) and creates the local `k3d` cluster.

## 2. Bootstrap Platform

```bash
./scripts/bootstrap-platform.sh
```

Creates necessary namespaces and installs ArgoCD.

## 3. Define Environment Topology (Declarative)

DeployGuard uses a declarative `deployguard.yaml` file to define the exact state of your local cluster. Create a minimal `deployguard.yaml` file in the root of the project:

```yaml
name: my-minimal-env
dependencies:
  - name: postgres
    repo: https://charts.bitnami.com/bitnami
    chart: postgresql
    version: "<SOME_VERSION>"
    set:
      - "auth.someproperty=my-postgres-value"

services:
  - name: sample-api
    depends_on:
      - postgres
    env:
      - SOME_KEY="some_value"
```

*For an advanced, enterprise-grade architecture example, see the [Test Scenario](test-scenario.md).*

## 4. Sync Environment

Apply your topology with a single command:

```bash
# Deploy the entire default environment
./scripts/sync-env.sh

# Deploy a focused subset of the environment (saves RAM)
./scripts/sync-env.sh --focus sample-api
```

This Orchestrator script will automatically parse your YAML, scaffold everything using modular Helm charts, build the necessary Docker images, and trigger a strict GitOps deployment via ArgoCD.

## Platform Architecture & Topologies (Under the Hood)

To fully leverage DeployGuard, it helps to understand how it operates behind the scenes:

1. **The Cluster (K3d & Docker):** DeployGuard provisions a lightweight, ephemeral K3s cluster running entirely inside Docker.
2. **Ingress & Networking (Traefik):** You don't need manual `kubectl port-forward` commands. DeployGuard uses Traefik as an Ingress controller, automatically routing traffic to your web services via `<service-name>.127.0.0.1.nip.io:8080`.
3. **Local GitOps Server (Nginx):** To strictly adhere to the GitOps methodology, the orchestration script packages your local Helm charts and serves them via an ephemeral Nginx container (`http://host.k3d.internal:8081`). ArgoCD dynamically fetches the manifests from this local server.
4. **Topologies & Orchestrator:** The `sync.py` orchestrator translates the agnostic `deployguard.yaml` directly into GitOps manifests and modular Helm charts. Developers can spin up only the exact subset of microservices they need using the `--focus` flag, heavily optimizing local CPU and RAM usage.

## Next Steps

Learn how to configure specific entities in DeployGuard:
- [Explore the Test Scenario](test-scenario.md)
- [Configure Services](services.md)
- [Add Dependencies](dependencies.md)
- [Mock External APIs](mocks.md)
- [Run E2E Tests](tests.md)
- [Initialize Database Data (Seeds)](seeds.md)