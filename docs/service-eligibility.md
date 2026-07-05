# Service Eligibility Contract

This document defines exactly when `scripts/add-service.sh` is expected to generate a working Helm chart and ArgoCD Application.

If a service meets all requirements below and still fails in local cluster deployment with DeployGuard scripts, it is considered a repository bug.

## Required Service Location

1. Service code must live in `app/<service-name>/`.
2. `<service-name>` must be lowercase, alphanumeric, and hyphen only.

## Required Files

1. `app/<service-name>/Dockerfile`

## Required Runtime Shape

1. Single container HTTP service.
2. Service must expose a health endpoint path provided to scaffold input.
3. Service must expose a Prometheus metrics endpoint path provided to scaffold input.
4. Service may optionally be stateful (creates a StatefulSet) if it requires a PVC mount, but must still expose HTTP health/metrics.

## Required Build/Deploy Assumptions

1. Docker image can be built locally from `app/<service-name>/`.
2. Service listens on a single main HTTP port and is reachable through Kubernetes Service mapping.
3. Scaffold supports defaults and optional overrides:
   - defaults: image repo `<service-name>`, image tag `v1`, container port `8000`, service port `80`, health path `/health`, metrics path `/metrics`
   - overrides: CLI flags (including `--storage-size`, `--storage-mount`) and optional `app/<service-name>/service.contract.env`

## Supported Technology Scope

1. Stack-agnostic HTTP services packaged as Docker images.
2. Any language/runtime is supported if the service contract is satisfied.

## Explicitly Unsupported Cases 

1. Multi-container pods or sidecar-dependent workloads.
2. Stateful services that require complex clustering (e.g. multi-node databases). Single-node HTTP-wrapped stateful services are supported.
3. Services without HTTP health and metrics endpoints.
4. Complex ingress, mTLS, or custom network policy requirements.
5. Direct remote Git repository onboarding (input is local service folder only).

## Validation Performed by `scripts/add-service.sh`

1. Path and naming checks.
2. Required file checks.
3. Scaffold configuration checks (ports and paths).
4. Generated Helm chart render check (`helm template`).
