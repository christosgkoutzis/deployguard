# External Dependency Eligibility Contract

This document defines exactly how DeployGuard supports external, third-party stateful or stateless dependencies (e.g., PostgreSQL, Redis, RabbitMQ) via Kubernetes GitOps and generic Secrets.

## The Core Concept
Instead of containerizing community tools manually in the `app/` directory, DeployGuard leverages ArgoCD to directly fetch and deploy standard Helm charts from public or private Helm repositories. 

## Validation Performed by `scripts/add-dependency.sh`
The script generates a raw ArgoCD Application definition and optionally a Kubernetes Secret for secure credential injection. It enforces:
1. Presence of a valid App Name, Helm Repository URL, and Chart Name.
2. Safe creation of Base64 encoded Kubernetes Secrets using the `--secret` flag.
3. Correct mapping of user-provided `--set` arguments to ArgoCD Helm parameters.

## Required Assumptions & Constraints
1. **No Local Code:** Dependencies deployed via this script cannot have local source code in `app/`. They are strictly remote Helm charts.
2. **Platform Layer:** Dependency names MUST be injected into the deployment lifecycle as `PLATFORM_APPS` in the `dev-deploy.sh` pipeline to prevent the build system from searching for a local Dockerfile.
3. **Init Jobs:** If a dependency requires schema initialization (e.g., a Database), the microservice consuming it MUST define an `INIT_COMMAND` in its `service.contract.env`. The platform will automatically wrap this command in a Kubernetes `Job` with a `pre-install` Helm hook, executing it securely before the microservice starts.

## Usage Example (Secure PostgreSQL)
To provision an external service securely via K8s Secrets:

```bash
./scripts/add-dependency.sh postgres \
  --repo [https://charts.bitnami.com/bitnami](https://charts.bitnami.com/bitnami) \
  --chart postgresql \
  --secret my-postgres-secret auth-password=secretpassword \
  --set auth.existingSecret=my-postgres-secret \
  --set auth.secretKeys.adminPasswordKey=auth-password
```