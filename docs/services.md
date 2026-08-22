# Services & Workers Eligibility Contract

This document defines exactly when the internal scaffolding (`scripts/add-service.sh`) is expected to generate a working Helm chart and ArgoCD Application. If a service meets all requirements below and still fails in local cluster deployment, it is considered a repository bug.

## Required Service Location & Files

1. By default, service code and its `Dockerfile` are expected in `services/<service-name>/`. You can place your code anywhere by defining a custom `build_path` in your topology YAML.
2. `<service-name>` must consist of lowercase letters, numbers, and hyphens only.

## Workload Archetypes

DeployGuard natively supports different architectural patterns via the `type` field in your `deployguard.yaml`:

* `webservice` (Default): Creates a Kubernetes Deployment, an internal K8s Service, an Ingress route, and enforces HTTP readiness probes.
* `worker`: Creates only a Kubernetes Deployment. Ideal for background processors, queue consumers, or async tasks that do not expose web ports.

## Required Runtime Shape

1. Single container HTTP service (or background worker).
2. Web services must expose a health endpoint path defined in the topology (or default `/health`).
3. The service may optionally be stateful (creates a `StatefulSet`) if it requires a PVC mount, but it must still expose an HTTP health endpoint.
4. The service must listen on a single main HTTP port and be reachable through K8s Service mapping.

## Customizing Environment Variables

DeployGuard supports a flexible, hybrid approach for injecting configuration into your services:

1. **Inline Overrides (`env`):** Best for platform-specific commands or simple variables.
2. **External Files (`env_file`):** Best for standard application environment variables. You can point this to `.env.development`, `.env.local`, or any custom env file residing inside the service directory (e.g., `env_file: .env.local`).

## Dynamic Service Configuration

You do not have to conform to the default `services/` folder, port `8000`, or `/health`. You can define them explicitly per service in your YAML:

```yaml
services:
  - name: legacy-api
    build_path: "./backend/legacy-api"
    port: 3000
    health_endpoint: "/api/status"
```

## Explicitly Unsupported Cases 

1. Multi-container pods or sidecar-dependent workloads.
2. Stateful services that require complex clustering (e.g., multi-node databases). Single-node HTTP-wrapped stateful services are supported.
3. Web services without an HTTP health endpoint.
4. Complex ingress, mTLS, or custom network policy requirements.
5. Direct remote Git repository onboarding (input must be a local folder).