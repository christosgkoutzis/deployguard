# Mock Services Eligibility Contract

This document defines exactly how DeployGuard supports local ephemeral mock services using WireMock. If a mock service meets the requirements below and fails to deploy via the local cluster scripts, it is considered a repository bug.

## Supported Technology Scope

1. **HTTP/HTTPS APIs Only:** The mock service uses WireMock, meaning it can only simulate RESTful or SOAP endpoints over HTTP.
2. **No Stateful/Binary Protocols:** You cannot mock raw databases (e.g., PostgreSQL, MySQL) or message brokers. WireMock strictly intercepts HTTP traffic. 

## Required Mock Location

1. Mock data must live in `mocks/<mock-name>/`.
2. `<mock-name>` must be lowercase, alphanumeric, and hyphen only.

## Required Files

1. At least one valid WireMock `.json` stub mapping file must exist inside `mocks/<mock-name>/`.

## Execution Requirements

Mock services are injected declaratively. You no longer need to pass environment variables manually or run scaffolding scripts. Add the mock to the `mocks` array in your topology YAML:

```yaml
mocks:
  - external-api-mock
```

The orchestrator script automatically parses this, creates the GitOps configuration, and injects your JSON stubs into an ephemeral K8s ConfigMap that mounts directly into the WireMock pod.