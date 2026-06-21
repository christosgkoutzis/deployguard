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

## 3) Scaffold Service Manifests (Template Flow)

Generate chart + ArgoCD app for each service in `app/<service-name>`:

```bash
./scripts/add-service.sh python-backend
./scripts/add-service.sh ruby-gateway
```

This creates:

- `platform/charts/python-backend/`
- `platform/charts/ruby-gateway/`
- `platform/gitops/python-backend.yaml`
- `platform/gitops/ruby-gateway.yaml`

## 4) Register Generated ArgoCD Applications

```bash
kubectl apply -f platform/gitops/python-backend.yaml
kubectl apply -f platform/gitops/ruby-gateway.yaml
```

## 5) Build, Import, Sync, and Wait

```bash
./scripts/dev-deploy.sh
```

Builds service images from `app/<service-name>`, imports them into k3d, syncs ArgoCD apps, and waits for health.

## 6) Run Verification

```bash
./scripts/verify.sh
```

Checks rollout, health endpoint, metrics endpoint, and Prometheus scraping.

## 7) Validate Service-to-Service Communication

Port-forward Ruby gateway and open/curl it:

```bash
kubectl -n deployguard port-forward svc/ruby-gateway-service 8080:80
curl http://127.0.0.1:8080/
```

Expected behavior: Ruby page includes a message fetched from Python backend.

Optional direct Python check:

```bash
kubectl -n deployguard port-forward svc/python-backend-service 8081:80
curl http://127.0.0.1:8081/message
```

## 8) Check ArgoCD and Prometheus

ArgoCD:

```bash
kubectl -n argocd port-forward svc/argocd-server 8082:80
```

Prometheus:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
```

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
