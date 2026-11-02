# Services and workers

A service is application code built from a local Dockerfile. DeployGuard can run it as a web service, a background worker, or a test Job.

## Run a small API

Create the following three files in your checkout. Run commands from the repository root. The examples in the other guides build on this API.

`my-app/api/server.py`:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.request import urlopen

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            data = {"status": "ok"}
        elif self.path == "/greeting":
            data = {"message": os.getenv("MESSAGE", "Hello from sample-api")}
            if os.getenv("GREETING_URL"):
                with urlopen(os.environ["GREETING_URL"], timeout=5) as response:
                    data["external"] = json.load(response)
        else:
            self.send_error(404)
            return
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
```

`my-app/api/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY server.py .
CMD ["python", "server.py"]
```

`my-app/deployguard.yaml`:

```yaml
apiVersion: deployguard/v1
name: deployguard
services:
  - name: sample-api
    build_path: api
    port: 8000
    health_endpoint: /health
```

After installing [the local tools](get-started.md#1-install), run:

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard setup --topology my-app/deployguard.yaml
./scripts/deployguard bootstrap --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml
curl --fail http://sample-api.127.0.0.1.nip.io:8080/greeting
```

The response is `{"message": "Hello from sample-api"}`.

The custom topology uses the same `name` and configured cluster as the demo. It can be deployed from the same checkout; unselected demo applications remain until you explicitly prune them. Do not change the environment name within an existing checkout's generated state. Use a separate checkout and cluster settings for isolation.

Each example below replaces `my-app/deployguard.yaml` with a complete configuration. Examples in other guides also start from this API; they are alternatives, not YAML blocks to concatenate.

## Add a worker

Create two more files.

`my-app/worker/worker.py`:

```python
import os
import time
from urllib.request import urlopen

while True:
    with urlopen(os.environ["API_URL"] + "/greeting", timeout=5) as response:
        print(response.read().decode(), flush=True)
    time.sleep(10)
```

`my-app/worker/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY worker.py .
CMD ["python", "-u", "worker.py"]
```

Replace `my-app/deployguard.yaml`:

```yaml
name: deployguard
services:
  - name: sample-api
    build_path: api
  - name: sample-worker
    type: worker
    build_path: worker
    depends_on: [sample-api]
    env:
      - API_URL=http://sample-api-service:80
```

```bash
./scripts/deployguard sync --topology my-app/deployguard.yaml --focus sample-worker
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard logs deployment/sample-worker-workload --tail=10
```

The worker prints the API's greeting every ten seconds. A web service gets a Deployment, Service, Ingress, and HTTP readiness probe. A worker gets a Deployment with no HTTP probe, Service, or Ingress. Worker readiness does not prove that its work is succeeding.

## Set environment variables

Save `my-app/api/app.env`:

```dotenv
MESSAGE=Hello from app.env
```

Replace `my-app/deployguard.yaml`:

```yaml
name: deployguard
services:
  - name: sample-api
    build_path: api
    env_file: app.env
    env:
      - MESSAGE=Hello from the topology
```

```bash
./scripts/deployguard sync --topology my-app/deployguard.yaml
curl --fail http://sample-api.127.0.0.1.nip.io:8080/greeting
```

The message is `Hello from the topology`: inline `env` overrides `env_file`. The file is parsed as dotenv data, not executed as shell code.

`${VARIABLE}` placeholders read from the repository's `.env` or process environment, with process variables taking precedence. Missing variables and duplicate inline keys are errors.

## Supply a password through a Secret

The installer-created `.env` already declares `POSTGRES_PASSWORD`. Review that local password, then replace `my-app/deployguard.yaml`:

```yaml
name: deployguard
secrets:
  - name: sample-credentials
    values: {password: POSTGRES_PASSWORD}
services:
  - name: sample-api
    build_path: api
    secret_env:
      DB_PASSWORD: {name: sample-credentials, key: password}
```

`POSTGRES_PASSWORD` is the host variable; `password` is the Kubernetes Secret key; `DB_PASSWORD` is the variable delivered to the container. The sample API does not use a database, but you can check the binding without printing the password:

```bash
./scripts/deployguard sync --topology my-app/deployguard.yaml
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard exec deployment/sample-api-workload -- python -c 'import os; assert os.environ["DB_PASSWORD"]; print("Password is configured")'
```

`env_from: [sample-credentials]` instead imports every Secret key under its own name. Do not repeat a variable in both `env` and `secret_env`. Keep credentials out of ordinary `env` entries: those entries enter generated Git snapshots; Secret values are sent directly to Kubernetes.

## Optional Vault bindings

Vault KV v2 can supply container environment variables through External Secrets Operator. An already initialized Vault server does not need a DeployGuard seeder.

For a concrete example, first run the bundled demo, which starts Vault and seeds `deployguard/python-backend`. Then replace `my-app/deployguard.yaml` with:

```yaml
name: deployguard
secrets:
  - name: sample-vault-token
    values: {token: VAULT_ROOT_TOKEN}
secret_stores:
  - name: sample-vault
    server: http://vault.${NAMESPACE}.svc.cluster.local:8200
    path: secret
    token_secret: {name: sample-vault-token, key: token}
services:
  - name: sample-api
    build_path: api
    external_secret:
      store: sample-vault
      path: deployguard/python-backend
```

```bash
./scripts/deployguard bootstrap --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard exec deployment/sample-api-workload -- python -c 'import os; assert os.environ["DB_URL"]; print("Vault value is configured")'
```

This example reuses the running demo Vault. Do not prune its applications while using it. For your own Vault, change the server, token source, and KV path. If a topology also starts or seeds Vault, declare those prerequisites with `depends_on`, as the demo does.

ESO runs in `external-secrets`, so an in-cluster Vault address must resolve from that namespace. Short names such as `vault` refer to a service in ESO's own namespace; the namespace-qualified address above reaches the demo Vault.

Each sync refreshes managed ExternalSecrets and restarts selected Deployments or StatefulSets when referenced Secret versions change. A Vault change needs another sync to reach running containers. Secret references do not encrypt local files; Vault dev mode and this setup are for local use.

## Requirements and limits

- Every service build context needs a file named `Dockerfile`. Paths resolve relative to the topology. Defaults are `services/<name>/`, or `tests/<name>/` for test services.
- Names are unique lowercase DNS labels, at most 40 characters.
- Web services listen on all interfaces and expose a successful HTTP health endpoint. Defaults are port 8000, `/health`, and one replica.
- Internal web Services are `<name>-service` on port 80; Deployments are `<name>-workload`.
- `command` overrides the container entry point and `args` supplies its arguments. Both are arrays; shell operators need an explicit shell.
- `resources` accepts Kubernetes requests and limits. Set them for your application rather than copying a budget from another service.
- Application charts use a single container. Service fields do not support sidecars, stateful clustering, advanced ingress/TLS, network policies, or prebuilt images.
- Builds use local folders. Topology fields do not configure remote Git checkout, custom Dockerfile names, build arguments, or build secrets.

Use a [dependency chart](dependencies.md) for other Kubernetes shapes. See [initialization](seeds.md) for migrations and [tests](tests.md) for test Jobs.
