# Get Started

This guide bootstraps DeployGuard from scratch, scaffolds service deployment assets, deploys a 2-service ecosystem (Ruby + Python), and validates the full flow.

## Prerequisites

1. Docker daemon running locally.
2. Internet access for image/chart downloads.
3. Shell access with permissions to run the scripts.

## 1) Create Local Cluster and Tooling

```bash
./scripts/setup.sh
```

Installs missing tools (`kubectl`, `k3d`, `helm`, `yq`) and creates the local k3d cluster.

## 2) Bootstrap Platform

```bash
./scripts/bootstrap-platform.sh
```

Creates namespaces and installs ArgoCD. Also registers the Prometheus ArgoCD app.

## 3) Define Environment Topology (Declarative)

DeployGuard uses a declarative `deployguard.yaml` file to define the exact state of your local cluster. Instead of manually running scaffolding scripts, you define your required services, dependencies, and mocks in one place.

Create a `deployguard.yaml` file in the root of the project:

```yaml
name: deployguard-local-env

platform_apps:
  - prometheus

dependencies:
  - name: postgres
    repo: [https://charts.bitnami.com/bitnami](https://charts.bitnami.com/bitnami)
    chart: postgresql
    version: "" # Leave empty to auto-resolve the latest stable version
    secret: 
      name: my-postgres-secret
      key_values:
        - "postgres-password=secretpassword"
    set:
      - "global.postgresql.auth.existingSecret=my-postgres-secret"
      - "auth.existingSecret=my-postgres-secret"
      - "architecture=standalone"
      - "primary.persistence.size=100Mi"
      - "fullnameOverride=postgres"

mocks:
  - external-api-mock

services:
  - name: python-backend
    env:
      - INIT_COMMAND="python migrate.py"
  - name: ruby-gateway
    env:
      - BACKEND_URL="http://python-backend-service:80"
```

### Customizing Environment Variables & Init Jobs
DeployGuard supports a flexible, hybrid approach for injecting configuration into your services:
1. **Inline Overrides (`env`):** Best for platform-specific commands (like `INIT_COMMAND` to run database migrations before the service starts) or simple variables.
2. **External Files (`env_file`):** Best for standard application environment variables. You can point this to `.env.development`, `.env.local`, or any custom env file residing inside the service directory (e.g., `env_file: .env.local`).

## 4) Sync Environment

Apply your topology with a single command:

```bash
./scripts/sync-env.sh
```

This Orchestrator script will automatically parse your YAML, scaffold everything using the Universal Helm Chart, build the necessary Docker images, and trigger a strict GitOps deployment via ArgoCD.

## 5) Run Verification

Because the environment is now fully dynamic, run the verification script by sourcing the topology output variables generated during the sync:

```bash
source .sync-env.env
PLATFORM_APPS="${PLATFORM_APPS_COMBINED}" MOCK_APP_NAMES="${MOCKS}" VERIFY_PROM_EXPECTED_JOBS="${SERVICES},prometheus" ./scripts/verify.sh
```

Checks rollout, health endpoint, metrics endpoint, and Prometheus scraping specifically for the apps defined in your topology.

## 6) Validate Service-to-Service Communication

All services are accessible out-of-the-box via Traefik Ingress on port 8080 using `nip.io` wildcard DNS. No port-forwarding required!

Open your browser or run:
```bash
curl [http://ruby-gateway.127.0.0.1.nip.io:8080/](http://ruby-gateway.127.0.0.1.nip.io:8080/)
```
Expected behavior: Ruby page includes a message fetched from Python backend and the Mock API.

Optional direct Python check:
```bash
curl [http://python-backend.127.0.0.1.nip.io:8080/message](http://python-backend.127.0.0.1.nip.io:8080/message)
```

## 7) Check Platform Ecosystem

ArgoCD Dashboard:
Open **[http://argocd.127.0.0.1.nip.io:8080](http://argocd.127.0.0.1.nip.io:8080)**
*(Username: `admin`, get password via `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`)*

Prometheus Dashboard:
Open **[http://prometheus.127.0.0.1.nip.io:8080](http://prometheus.127.0.0.1.nip.io:8080)**

## Acceptance Criteria

1. `./scripts/sync-env.sh` completes without sync/health failures.
2. `./scripts/verify.sh` passes (using the topology env variables).
3. Ruby gateway returns content that includes Python backend response.
4. Prometheus shows both service jobs as healthy targets.
5. ArgoCD shows both service apps as Synced and Healthy.

## Notes on Generated Files

Generated GitOps app YAMLs are intentionally ignored by git. This keeps the repository template-first and avoids committing scaffold outputs.

## Behind the Scenes: Local GitOps Server

To maintain the template-first approach without breaking GitOps:

1. `sync-env.sh` (via `dev-deploy.sh` under the hood) packages the Universal Helm Chart and serves it via a lightweight, ephemeral `nginx` container on port `8081`.
2. The generated ArgoCD apps point to `http://host.k3d.internal:8081`, allowing the k3d cluster to fetch the local charts dynamically.
3. Scripts are built to fail-fast and auto-cleanup if a scaffold step fails, ensuring no partial or corrupted states.

## CI/CD Guardrails

This repository includes a GitHub Actions workflow (`.github/workflows/cluster-integration.yml`). On every push to the master branch or pull request, it runs a full **End-to-End Cluster Validation**. 

It dynamically spins up an ephemeral k3d cluster, bootstraps ArgoCD, applies the `deployguard.yaml` topology, and runs the entire `sync-env` and `verify` flow. This ensures no change breaks the local GitOps pipeline.