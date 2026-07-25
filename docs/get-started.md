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
    repo: https://charts.bitnami.com/bitnami
    chart: postgresql
    version: ""
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
  - name: kafka
    repo: https://charts.bitnami.com/bitnami
    chart: kafka
    version: ""
    set:
      - "kraft.enabled=true"
      - "zookeeper.enabled=false"
      - "replicaCount=1"
      - "listeners.client.protocol=PLAINTEXT"
      - "extraEnvVars[0].name=KAFKA_HEAP_OPTS"
      - "extraEnvVars[0].value=-Xmx256m -Xms256m"

mocks:
  - external-api-mock

services:
  - name: python-backend
    depends_on:
      - postgres
      - kafka
    env:
      - INIT_COMMAND="python migrate.py"
  - name: ruby-gateway
    depends_on:
      - python-backend
    env:
      - BACKEND_URL="http://python-backend-service:80"
  - name: python-worker
    type: worker
    depends_on:
      - postgres
      - kafka
      - external-api-mock
```
### Dependency Graph & Event-Driven Architecture
DeployGuard introduces a `depends_on` field. This allows the orchestrator to build a dependency graph for your microservices. 
In our example, the system uses an **Event-Driven Architecture**:
1. **Ruby Gateway** depends on **Python Backend**.
2. **Python Backend** writes to **PostgreSQL** and publishes events to **Kafka**.
3. **Python Worker** consumes events from **Kafka**, validates them via the **External API Mock**, and updates **PostgreSQL**.

The included Kafka dependency is a lightweight KRaft-mode emulator with a strict 256MB memory limit, ensuring it runs smoothly on local environments without consuming excessive resources.

### Workload Archetypes
DeployGuard natively supports different architectural patterns via the `type` field in your `deployguard.yaml`:
* `webservice` (Default): Creates a Deployment, an internal Service, an Ingress route, and enforces HTTP readiness probes.
* `worker`: Creates only a Deployment. Ideal for background processors, queue consumers, or async tasks that do not expose web ports.

### Customizing Environment Variables & Init Jobs
DeployGuard supports a flexible, hybrid approach for injecting configuration into your services:
1. **Inline Overrides (`env`):** Best for platform-specific commands (like `INIT_COMMAND` to run database migrations before the service starts) or simple variables.
2. **External Files (`env_file`):** Best for standard application environment variables. You can point this to `.env.development`, `.env.local`, or any custom env file residing inside the service directory (e.g., `env_file: .env.local`).

## 4) Sync Environment

Apply your topology with a single command:

```bash
# Deploy the entire environment
./scripts/sync-env.sh

# OR: Deploy a focused subset of the environment
./scripts/sync-env.sh --focus ruby-gateway
```

This Orchestrator script will automatically parse your YAML, scaffold everything using the Universal Helm Chart, build the necessary Docker images, and trigger a strict GitOps deployment via ArgoCD.

The --focus Flag:
By using --focus <service-name>, DeployGuard reads the depends_on graph in your YAML and deploys only the requested service along with its direct dependencies. This dramatically saves local CPU/RAM resources (e.g., focusing on ruby-gateway will skip provisioning Kafka, the mock, and the worker entirely).

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
Expected behavior: 
1. Ruby page includes a message fetched from the Python backend and the Mock API.
2. Writing a greeting via the UI triggers a POST to the Python backend.
3. The Python backend writes to PostgreSQL and publishes an event to Kafka.
4. The Python Worker consumes the Kafka event, validates via the Mock API, and updates the database.

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