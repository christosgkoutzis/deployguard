# Service Eligibility Contract

This document defines exactly when `scripts/add-service.sh` is expected to generate a working Helm chart and ArgoCD Application.

If a service meets all requirements below and still fails in local cluster deployment with DeployGuard scripts, it is considered a repository bug.

## Required Service Location & Files
1. By default, service code and its `Dockerfile` are expected in `app/<service-name>/`. You can now place your code anywhere by defining a custom `build_path` in your topology YAML.
2. `<service-name>` must be lowercase, alphanumeric, and hyphen only.

## Required Runtime Shape
1. Single container HTTP service.
2. Service must expose a health endpoint path defined in the topology (or default `/health`).
3. Service may optionally be stateful (creates a StatefulSet) if it requires a PVC mount, but must still expose HTTP health.

## Required Build/Deploy Assumptions
1. The Docker image can be built locally using the provided `build_path` (or default `app/` folder).
2. Service listens on a single main HTTP port and is reachable through Kubernetes Service mapping.
3. Scaffold uses the following defaults, which can be dynamically overridden in your topology YAML:
   - Container Port: Defaults to `8000`. Override with `port: <number>`.
   - Health Check: Defaults to `/health`. Override with `health_endpoint: "<path>"`.
   - Service Port: Fixed at `80`.
   - Overrides: CLI flags (including `--storage-size`, `--storage-mount`) and optional `service.contract.env` (or custom `env_file` defined in YAML).

## Supported Technology Scope

1. Stack-agnostic HTTP services packaged as Docker images.
2. Any language/runtime is supported if the service contract is satisfied.

## Explicitly Unsupported Cases 

1. Multi-container pods or sidecar-dependent workloads.
2. Stateful services that require complex clustering (e.g. multi-node databases). Single-node HTTP-wrapped stateful services are supported.
3. Services without HTTP health endpoint.
4. Complex ingress, mTLS, or custom network policy requirements.
5. Direct remote Git repository onboarding (input is local service folder only).

## Validation Performed by `scripts/add-service.sh`

1. Path and naming checks.
2. Required file checks.
3. Scaffold configuration checks (ports and paths).
4. Generated Helm chart render check (`helm template`).
