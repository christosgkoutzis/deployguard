# Mock an HTTP API

Use a WireMock mock when your application needs a predictable HTTP response instead of a real external API. For example, a greeting API can return the same JSON on every test run.

Start with the [small API example](services.md#run-a-small-api), including its Python file and Dockerfile.

## Add a response

Save `my-app/mocks/sample-mock/greeting.json`:

```json
{
  "request": {"method": "GET", "url": "/api/greeting"},
  "response": {
    "status": 200,
    "jsonBody": {"message": "Hello from sample-mock"}
  }
}
```

Replace `my-app/deployguard.yaml` with:

```yaml
name: deployguard
mocks:
  - sample-mock
services:
  - name: sample-api
    build_path: api
    depends_on: [sample-mock]
    env:
      - GREETING_URL=http://sample-mock-service:80/api/greeting
```

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml --focus sample-api
curl --fail http://sample-api.127.0.0.1.nip.io:8080/greeting
```

The API calls the mock and returns:

```json
{
  "message": "Hello from sample-api",
  "external": {"message": "Hello from sample-mock"}
}
```

`depends_on` ensures that focusing on the API also deploys its mock. Other pods use `sample-mock-service:80`. You can also request the mock directly at `http://sample-mock.127.0.0.1.nip.io:8080/api/greeting` with the default host settings.

## Change a response

Edit `greeting.json` and run the same sync command again. A mapping change restarts WireMock so it loads the new response. An unchanged mapping keeps the current pod.

Each mock needs at least one JSON mapping in `mocks/<name>/`, relative to the topology file. Each file must contain `request` and `response` objects. WireMock checks the detailed mapping rules when it starts.

Mappings are stored in a Kubernetes ConfigMap. Keep them small; nested response-file directories are not supported by the built-in chart.

WireMock handles HTTP, including REST and SOAP. It does not replace a database or a message broker. Use [dependency charts](dependencies.md) for those protocols.
