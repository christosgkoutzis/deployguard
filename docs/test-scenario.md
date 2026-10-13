# The DeployGuard Test Scenario

DeployGuard includes a local demo of services communicating through HTTP, events, and queued tasks. It validates the platform and provides a reference topology; its technologies do not constrain your own applications.

## Architecture

The demo connects these applications and dependencies:

1. **Ruby Gateway** calls **Python Backend**.
2. **Python Backend** reads **Redis**, falling back to **PostgreSQL** on a cache miss.
3. Writes enter **PostgreSQL** and publish an event to **Kafka**.
4. **HashiCorp Vault** holds application credentials, with environment variables as a fallback.
5. **Python Worker** consumes Kafka events, validates through **External API Mock**, updates PostgreSQL, and indexes into **Elasticsearch**.
6. **Report Worker** consumes export tasks from **RabbitMQ**, queries PostgreSQL, and uploads CSV reports to **MinIO**.
7. **Kafbat UI** and **Dozzle** provide topic/event and pod-log interfaces.

The topology declares prerequisites: Vault starts before its seeder, then the SecretStore, then service credentials and initialization. Workers depend on backend initialization. Tests require both workers and the mock.

## Validating Service-to-Service Communication

After the [setup workflow](get-started.md), open the gateway or request it:

```bash
curl http://ruby-gateway.127.0.0.1.nip.io:8080/
```

Use your configured domain and ingress port when changing defaults.

### Expected UI Behavior

1. **Sync Fetch:** The page includes both the Python backend response and mocked greeting.
2. **Custom Write:** Submit a greeting to write PostgreSQL and publish to Kafka.
3. **Async Validation:** The Python Worker validates the event through the mock, updates its status to Approved, and indexes it in Elasticsearch.
4. **Cached Read:** Reading the latest greeting checks Redis before PostgreSQL.
5. **Full-Text Search:** Search returns Elasticsearch results for the greeting.
6. **CSV Export:** Generate a report through RabbitMQ and the Report Worker, then obtain its MinIO presigned download URL.

The demo's S3 endpoint is `http://minio:9000`, which is reachable inside the cluster. Its presigned download link therefore also uses this internal hostname. The E2E suite downloads and validates the CSV inside Kubernetes. Host-browser access to that URL requires routing the signed hostname and port to MinIO; ingress access to the gateway alone does not make the S3 URL host-accessible. Preserve the signed host rather than rewriting the URL.

## Acceptance Criteria

1. Sync completes without deployment, initialization, or health failures.
2. Verify succeeds using the recorded inventory, without sourcing topology output variables.
3. Selected Applications show the requested revision as Synced and Healthy; registered test Jobs may be Suspended.
4. The gateway displays both backend and mock responses.
5. The E2E Job verifies that its written greeting is approved, cached, indexed, and present in a downloaded CSV.
6. Repeated sync and explicit test execution also succeed.

```bash
./scripts/deployguard sync
./scripts/deployguard verify
./scripts/deployguard test e2e-tests
```

A fresh `--focus e2e-tests` selects the full request-chain prerequisites while leaving Dozzle and Kafbat out. CI first verifies and tests that focused environment, then expands to the full topology on the same cluster only after the focused checks pass. Full deployment includes Dozzle and Kafbat. Focus switching retains previously selected applications unless pruning is requested.

## Inspecting the Local Environment

Examples below target the default cluster explicitly. Change the context, namespace, and names for a separate environment.

### ⚙️ Cluster Management

```bash
k3d cluster stop control-plane-cluster
k3d cluster start control-plane-cluster
```

Deleting a cluster removes its local environment. Use `k3d cluster delete <name>` only when intentionally resetting that specific cluster.

### 📦 Kubernetes & Pods

```bash
kubectl --context k3d-control-plane-cluster -n deployguard get pods
kubectl --context k3d-control-plane-cluster -n deployguard logs -f -l app=python-backend
POD_NAME=replace-with-a-pod-name
kubectl --context k3d-control-plane-cluster -n deployguard describe pod "$POD_NAME"
kubectl --context k3d-control-plane-cluster -n deployguard exec -it "$POD_NAME" -- /bin/sh
```

Use sync for source changes; Skaffold rebuilds the affected image and ArgoCD deploys its new reference.

### 🔌 Database & Broker Access

```bash
kubectl --context k3d-control-plane-cluster -n deployguard port-forward svc/postgres 5432:5432
kubectl --context k3d-control-plane-cluster -n deployguard port-forward svc/redis-master 6379:6379
kubectl --context k3d-control-plane-cluster -n deployguard port-forward svc/rabbitmq 5672:5672
```

These commands run until stopped and expose the selected database or broker locally.

### ☸️ Helm & GitOps

```bash
kubectl --context k3d-control-plane-cluster -n argocd get applications
helm --kube-context k3d-control-plane-cluster list -n argocd
```

Helm lists bootstrap releases; ArgoCD renders and reconciles application charts. Use its dashboard for per-application events and initialization-hook failures.

### 🐳 Docker Source Server

```bash
docker logs deployguard-source-control-plane-cluster
```

The container serves the separate generated Git repository used by ArgoCD.

## Clearing the Test Scenario

```bash
./scripts/deployguard clear-scenario
# Keep the local Kafka and RabbitMQ charts
./scripts/deployguard clear-scenario --skip-dependencies
```

The command moves only known demo assets into `.local/state/scenario-backups/<id>/`. Custom application files, generic charts, tool tests, and running cluster resources are retained. Restore files from that backup if needed. The demo topology remains: replace it before the next validation or sync. Clearing files does not prune existing cluster resources.
