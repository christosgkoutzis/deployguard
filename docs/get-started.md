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

Installs missing tools (`kubectl`, `k3d`, `helm`) and creates the local k3d cluster.

## 2) Bootstrap Platform

```bash
./scripts/bootstrap-platform.sh
```

Creates namespaces and installs ArgoCD. Also registers the Prometheus ArgoCD app.

## 3) Scaffold Services & Dependencies

DeployGuard supports generic third-party dependencies securely via Kubernetes Secrets and Helm hooks. 

First, add an external dependency (e.g., PostgreSQL) with auto-generated secrets:
```bash
    ./scripts/add-dependency.sh postgres \
      --repo https://charts.bitnami.com/bitnami \
      --chart postgresql \
      --version 15.1.0 \
      --secret my-postgres-secret postgres-password=secretpassword \
      --set global.postgresql.auth.existingSecret=my-postgres-secret \
      --set auth.existingSecret=my-postgres-secret \
      --set architecture=standalone \
      --set primary.persistence.size=100Mi \
      --set fullnameOverride=postgres
```

Then, generate chart + ArgoCD app for each internal service:
```bash
./scripts/add-service.sh python-backend
./scripts/add-service.sh ruby-gateway
```

### Customizing Scaffold Outputs & Init Jobs
If your service requires database migrations, custom ports, or storage, create a `service.contract.env` file in the service directory **before** running `add-service.sh`. 

Example `app/python-backend/service.contract.env` defining a pre-install schema migration Hook:
```env
INIT_COMMAND="python migrate.py"
```

## 4) Build, Import, Sync, and Wait

```bash
./scripts/dev-deploy.sh
```
Builds service images, imports them into k3d, automatically registers the ArgoCD apps, triggers the sync, and waits for health.

## 5) Run Verification

```bash
./scripts/verify.sh
```

Checks rollout, health endpoint, metrics endpoint, and Prometheus scraping.

*Note: The verification checks are strict. If any endpoint is unreachable or a metric format is missing, the script will halt immediately and explicitly print the failing service and endpoint.*

## 6) Validate Service-to-Service Communication

All services are accessible out-of-the-box via Traefik Ingress on port 8080 using `nip.io` wildcard DNS. No port-forwarding required!

Open your browser or run:
```bash
curl http://ruby-gateway.127.0.0.1.nip.io:8080/
```
Expected behavior: Ruby page includes a message fetched from Python backend and the Mock API.

Optional direct Python check:
```bash
curl http://python-backend.127.0.0.1.nip.io:8080/message
```

## 7) Check Platform Ecosystem

ArgoCD Dashboard:
Open **[http://argocd.127.0.0.1.nip.io:8080](http://argocd.127.0.0.1.nip.io:8080)**
*(Username: `admin`, get password via `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`)*

Prometheus Dashboard:
Open **[http://prometheus.127.0.0.1.nip.io:8080](http://prometheus.127.0.0.1.nip.io:8080)**

## Acceptance Criteria

1. `./scripts/dev-deploy.sh` completes without sync/health failures.
2. `./scripts/verify.sh` passes.
3. Ruby gateway returns content that includes Python backend response.
4. Prometheus shows both service jobs as healthy targets.
5. ArgoCD shows both service apps as Synced and Healthy.

## Notes on Generated Files

Generated charts and generated ArgoCD app YAMLs are intentionally ignored by git. This keeps the repository template-first and avoids committing scaffold outputs.

## Behind the Scenes: Local GitOps Server

Because the generated Helm charts are `.gitignore`d, the ArgoCD application cannot pull them from the remote GitHub repository. To maintain the template-first approach without breaking GitOps:

1. `dev-deploy.sh` packages the locally generated charts and serves them via a lightweight, ephemeral `nginx` container on port `8081`.
2. The generated ArgoCD apps point to `http://host.k3d.internal:8081`, allowing the k3d cluster to fetch the local charts dynamically.
3. Scripts are built to fail-fast and auto-cleanup if a scaffold step fails, ensuring no partial or corrupted states.

## CI/CD Guardrails

This repository includes a GitHub Actions workflow (`.github/workflows/cluster-integration.yml`). On every push to the master branch or pull request, it runs a full **End-to-End Cluster Validation**. 

It dynamically spins up an ephemeral k3d cluster, bootstraps ArgoCD, scaffolds the sample services, and runs the entire `dev-deploy` and `verify` flow. This ensures no change breaks the local GitOps pipeline.
