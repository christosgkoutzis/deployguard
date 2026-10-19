# Services & Workers

Declare application services and background workers under `services` in your topology. DeployGuard builds their Docker contexts and deploys them with the appropriate chart.

## Required Service Location & Files

1. Application services default to `services/<name>/`; test services default to `tests/<name>/`.
2. Custom build_path values point to local Docker contexts relative to the topology.
3. Every context must contain a Dockerfile.
4. Names must be unique lowercase DNS labels of at most 40 characters.

## Workload Archetypes

- webservice (default): Deployment, internal Service, Ingress, and HTTP readiness probe.
- worker: Deployment without an HTTP probe, Service, or Ingress.
- test: Suspended Job executed through the [test runner](tests.md).

## Required Runtime Shape

Applications use a single-container stateless Deployment, or a single-container test Job. Web applications must listen on all interfaces and expose a successful HTTP health endpoint. Workers must remain running without needing an HTTP port.

```yaml
services:
  - name: sample-api
    build_path: ./backend/sample-api
    port: 3000
    health_endpoint: /api/status
    resources:
      requests: {cpu: 100m, memory: 128Mi}
      limits: {memory: 256Mi}
  - name: queue-consumer
    type: worker
    build_path: ./background/consumer
    depends_on: [sample-api]
```

Defaults are port 8000, health path /health, and one replica. The internal Service is `<name>-service` on port 80; other pods use `http://<name>-service:80`. Deployment names are `<name>-workload`.

## Customizing Environment Variables

An env_file is parsed as dotenv data, not sourced as shell code. It resolves inside the build context. Inline env entries override the file; surrounding quotes are accepted. Placeholders resolve from the repository .env and process environment, with process variables taking precedence. Missing variables and duplicate inline keys are errors.

```yaml
services:
  - name: sample-api
    build_path: ./backend/sample-api
    env_file: .env.development
    env:
      - APP_MODE=local
      - PUBLIC_URL=http://sample-api.${CLUSTER_DOMAIN}:${INGRESS_PORT}
    command: [python, server.py]
    args: [--verbose]
```

Command and args are container argument arrays. An init_command or INIT_COMMAND env entry defines an initialization hook; see [Seeds](seeds.md).

## Secrets Management

Services that do not need secrets require no Vault or ESO configuration. For local credentials, declare a Kubernetes Secret and refer to its keys:

```yaml
secrets:
  - name: database-credentials
    values:
      password: DATABASE_PASSWORD
services:
  - name: sample-api
    secret_env:
      DB_PASSWORD: {name: database-credentials, key: password}
```

Set DATABASE_PASSWORD in your .env or terminal environment. DeployGuard writes its value directly to the Kubernetes Secret; generated deployment configuration contains only the Secret name and key. `env_from: [database-credentials]` imports every key. Do not duplicate a variable in env and secret_env.

External Secrets Operator (ESO) reads credentials from Vault into Kubernetes Secrets for your services. To use Vault KV v2, declare a secret store and service binding:

```yaml
secrets:
  - name: vault-token
    values: {token: VAULT_ROOT_TOKEN}
secret_stores:
  - name: vault-store
    server: http://vault.${NAMESPACE}.svc.cluster.local:8200
    path: secret
    token_secret: {name: vault-token, key: token}
    depends_on: [vault-seeder]
services:
  - name: sample-api
    external_secret:
      store: vault-store
      path: applications/sample-api
```

Use a namespace-qualified Vault address: ESO connects from the `external-secrets` namespace, so a short hostname such as `vault` does not resolve to the application namespace. `${NAMESPACE}` uses your configured application namespace.

Declare vault-seeder and its Vault prerequisite in the same topology. The store dependency is added automatically to the service graph. ESO extracts the path into `<name>-secret`; startup waits for successful synchronization. Rerun bootstrap when adding stores to an operator-free cluster.

On sync, DeployGuard refreshes managed ExternalSecrets and rolls selected Deployments and StatefulSets when their referenced Secret versions change. Vault changes require another sync to reach running containers; DeployGuard does not add a background restart controller.

Kubernetes Secrets and Vault dev mode serve the disposable local environment. Secret references do not encrypt local files or turn this into a production secrets platform.

## Explicitly Unsupported Cases

1. Multi-container pods or workloads requiring sidecars.
2. Stateful application clustering through service fields; use a dependency chart.
3. Web services without an HTTP health endpoint.
4. Advanced ingress, mTLS, or network policy configuration through service fields.
5. Direct remote Git onboarding; build input must be a local folder.

Use a custom dependency chart for Kubernetes shapes outside these archetypes.
