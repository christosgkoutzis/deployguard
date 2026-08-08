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

Creates namespaces and installs ArgoCD.

## 3) Define Environment Topology (Declarative)

DeployGuard uses a declarative `deployguard.yaml` file to define the exact state of your local cluster. Instead of manually running scaffolding scripts, you define your required services, dependencies, and mocks in one place.

Create a `deployguard.yaml` file in the root of the project:

```yaml
name: deployguard-local-env

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
    repo: http://host.k3d.internal:8081
    chart: confluent-kafka
    version: "0.1.0"
    set:
      - "image.tag=8.0.6"
      - "heapOpts=-Xms256m -Xmx256m"

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

In our example, the system uses a full **Enterprise Event-Driven Architecture**:
1. **Ruby Gateway** depends on **Python Backend**.
2. **Python Backend** relies on **Redis** for fast caching. If a cache miss occurs, it queries **PostgreSQL**.
3. **Python Backend** writes new events to **PostgreSQL** and publishes them to **Kafka**.
4. **Python Backend** integrates with **HashiCorp Vault** for secure credential management (Graceful Fallback).
5. **Python Worker** consumes events from **Kafka**, validates them via the **External API Mock**, updates **PostgreSQL**, and indexes data into **Elasticsearch**.
6. **Report Worker** consumes async export tasks from **RabbitMQ**, queries the DB, and uploads CSV reports to **MinIO** (S3 compatible storage).

The included Kafka dependency is a lightweight single-node Confluent Kafka KRaft chart. Redis is deployed as a standalone cache without auth. Elasticsearch is deployed as a single node with strict JVM memory limits (`-Xmx512m`) to prevent local environment starvation. RabbitMQ is provisioned via a native, lightweight Kubernetes Deployment using the official management image, ensuring an enterprise-grade but ephemeral local broker.

The included Kafka dependency is a lightweight single-node Confluent Kafka KRaft chart for local development. It uses Confluent Platform `8.0.6`, which maps to Apache Kafka 4.0.x. It exposes the standard broker endpoint at `kafka:9092`, uses `emptyDir` storage instead of a PVC, and runs without ZooKeeper. The default heap is 256Mi with conservative CPU and memory requests so the local cluster stays responsive while still exercising the real Kafka protocol used by the services.

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
By using --focus <service-name>, DeployGuard reads the depends_on graph in your YAML and deploys only the requested service plus its recursive dependencies. This saves local CPU/RAM by skipping unrelated workloads. For example, focusing on `ruby-gateway` still deploys `python-backend`, PostgreSQL, and Kafka because they are required by the dependency graph, but it skips `python-worker` and `external-api-mock`.

## 5) Run Verification

Because the environment is now fully dynamic, run the verification script by sourcing the topology output variables generated during the sync:

```bash
source .sync-env.env
MOCK_APP_NAMES="${MOCKS}" \
./scripts/verify.sh
```

Checks rollout, health endpoint, specifically for the apps defined in your topology.

## 6) Validate Service-to-Service Communication

All services are accessible out-of-the-box via Traefik Ingress on port 8080 using `nip.io` wildcard DNS. No port-forwarding required!

Open your browser or run:
```bash
curl [http://ruby-gateway.127.0.0.1.nip.io:8080/](http://ruby-gateway.127.0.0.1.nip.io:8080/)
```

Expected behavior: 
1. **Sync Fetch:** Ruby page includes a message fetched from the Python backend and the Mock API.
2. **Custom Write:** Submitting a custom greeting triggers a POST to the Python backend, writes to PostgreSQL, and publishes to Kafka.
3. **Async Validation:** The Python Worker consumes the Kafka event, validates via the Mock API, updates Postgres, and indexes into Elasticsearch.
4. **Cached Read:** Reading the latest greeting hits Redis (Cache) first, falling back to PostgreSQL if not found.
5. **Full-Text Search:** Searching queries Elasticsearch directly.
6. **CSV Export (MinIO/RabbitMQ):** Generating a report pushes a task to RabbitMQ. The Report Worker processes it and uploads a CSV to MinIO. Clicking download serves the file via an S3 Presigned URL generated by MinIO.

Optional direct Python check:
```bash
curl [http://python-backend.127.0.0.1.nip.io:8080/message](http://python-backend.127.0.0.1.nip.io:8080/message)
```

## 7) Check Platform Ecosystem & Observability

You have instant access to multiple Web UIs for cluster management and live debugging, without needing terminal commands:

* **ArgoCD Dashboard (GitOps):** 
  Open **[http://argocd.127.0.0.1.nip.io:8080](http://argocd.127.0.0.1.nip.io:8080)**
  *(Username: `admin`, get password via `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`)*

* **Dozzle (Live Pod Logs):**
  Open **[http://dozzle.127.0.0.1.nip.io:8080](http://dozzle.127.0.0.1.nip.io:8080)** to view a real-time stream of all active pod logs.

* **Kafbat UI (Kafka Topic & Event Explorer):**
  Open **[http://kafka-ui.127.0.0.1.nip.io:8080](http://kafka-ui.127.0.0.1.nip.io:8080)** to instantly view live broker metrics, explore topics, and inspect events.

## Acceptance Criteria

1. `./scripts/sync-env.sh` completes without sync/health failures.
2. `./scripts/verify.sh` passes (using the topology env variables).
3. Ruby gateway returns content that includes Python backend response.
4. ArgoCD shows the selected application graph as Synced and Healthy.

## Notes on Generated Files

Generated GitOps app YAMLs are intentionally ignored by git. This keeps the repository template-first and avoids committing scaffold outputs.

## Behind the Scenes: Local GitOps Server

To maintain the template-first approach without breaking GitOps:

1. `sync-env.sh` (via `dev-deploy.sh` under the hood) packages the Universal Helm Chart, mock charts, and the local Confluent Kafka chart, then serves them via a lightweight, ephemeral `nginx` container on port `8081`.
2. Generated ArgoCD apps for local charts point to `http://host.k3d.internal:8081`, allowing the k3d cluster to fetch those charts dynamically.
3. Scripts are built to fail-fast and auto-cleanup if a scaffold step fails, ensuring no partial or corrupted states.

## Local Kafka Design

DeployGuard uses a small local chart in `platform/confluent-kafka-chart` instead of overriding a third-party chart image. The chart runs `confluentinc/cp-kafka:8.0.6` in KRaft mode as a single Deployment with one replica. It is intentionally ephemeral: Kafka data lives in `emptyDir` and is discarded when the pod is recreated. Kubernetes service-link environment injection is disabled for this pod so generated variables such as `KAFKA_PORT` cannot conflict with Confluent's startup scripts.

This keeps local deployments light while preserving compatibility with services that expect a normal Kafka broker. The stable service address is `kafka:9092`, auto topic creation is enabled, and internal topics use replication factor `1`, which is appropriate for single-node local development.

## CI/CD Guardrails

This repository includes a GitHub Actions workflow (`.github/workflows/cluster-integration.yml`). On every push to the master branch or pull request, it runs a full **End-to-End Cluster Validation**. 

It dynamically spins up an ephemeral k3d cluster, bootstraps ArgoCD, applies the `deployguard.yaml` topology, and runs the entire `sync-env` and `verify` flow. This ensures no change breaks the local GitOps pipeline.

The workflow keeps a generic failure-debug step that prints ArgoCD application state, deployguard workloads, non-running pod descriptions, recent logs, and recent events. Keep this step in CI: it is low-risk, runs only on failure, and makes infrastructure failures diagnosable without reproducing them locally.