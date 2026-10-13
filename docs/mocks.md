# Mock Services

DeployGuard supports local HTTP API mocks through WireMock. Mocks are graph entities managed by ArgoCD.

## Supported Technology Scope

1. WireMock simulates HTTP APIs, including REST and SOAP requests.
2. Database, broker, and binary protocols need real dependencies or a purpose-built tool.
3. Built-in ingress exposes HTTP; topology fields do not configure TLS.

## Required Mock Location & Files

Put at least one JSON mapping in `mocks/<name>/`, relative to the topology. Names must be unique lowercase DNS labels of at most 40 characters. Each mapping object must contain `request` and `response`; WireMock checks its detailed mapping semantics at runtime.

```json
{
  "request": {"method": "GET", "url": "/api/greeting"},
  "response": {
    "status": 200,
    "jsonBody": {"message": "Hello from the mocked API!"}
  }
}
```

Mappings are mounted from a ConfigMap. Keep the combined content within Kubernetes ConfigMap limits. Nested fixture directories and large file-backed responses are not supported by the built-in chart.

## Declarative Configuration

```yaml
mocks:
  - external-api-mock
services:
  - name: sample-api
    depends_on: [external-api-mock]
    env:
      - EXTERNAL_API_URL=http://external-api-mock-service:80
```

A declared mock is selected in full syncs. Add it to `depends_on` when a service or test also needs it in focus mode. The chart mounts mappings, exposes `<name>-service:80`, and creates ingress at `<name>.<CLUSTER_DOMAIN>`. Verification checks rollout and WireMock's `/__admin/` endpoint.

Edit mappings and sync again. Changed mappings trigger a WireMock rollout so the running server loads them; unchanged mappings keep the current pod. No separate scaffolding command is needed.
