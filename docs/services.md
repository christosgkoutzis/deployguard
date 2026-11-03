# Services and workers

The [test scenario](test-scenario.md) already contains web services and workers. Use their entries in [deployguard.yaml](../deployguard.yaml) and their Dockerfiles as references. Configuration excerpts below belong to that file; they are not replacement topologies.

## Follow an HTTP request

The [Ruby gateway](../services/ruby-gateway/main.rb) calls the [Python backend](../services/python-backend/main.py). Its topology entry is:

```yaml
- name: ruby-gateway
  depends_on:
    - python-backend
  env:
    - BACKEND_URL=http://python-backend-service:80
```

After [setup and bootstrap](get-started.md), deploy the backend and its prerequisites, then request its message:

```bash
./scripts/deployguard sync --focus python-backend
curl --fail http://python-backend.127.0.0.1.nip.io:8080/message
```

The response contains `"message":"Hello from python-backend!"`. This selection does not include the gateway or workers. Use `sync --focus e2e-tests` for the complete request flow.

The backend's [Dockerfile](../services/python-backend/Dockerfile) starts it on `0.0.0.0:8000`. DeployGuard creates a Deployment to keep its pod running, a Service on port 80 for cluster access, and an Ingress rule for its hostname. A readiness probe checks `/health` before the pod receives Service traffic.

Built-in service Deployments are named `<name>-workload`; web Services are `<name>-service`. For example, the backend uses `python-backend-workload` and `python-backend-service`.

## Run background work

The scenario declares `python-worker` and `report-worker` with `type: worker`. They consume Kafka events and RabbitMQ tasks respectively. See their [Kafka worker](../services/python-worker/worker.py) and [report worker](../services/report-worker/report-worker.py) implementations.

Workers get a Deployment without an HTTP probe, Service, or Ingress. A ready worker pod does not prove that it processed a message; the [integration suite](tests.md) checks that behavior.

## Configure environment and secrets

`BACKEND_URL` above is ordinary configuration. Use `env_file` for a dotenv file relative to the service's build context; inline `env` takes precedence. Dotenv files are parsed as data, not executed as shell scripts. `${VARIABLE}` placeholders read the checkout's `.env` or process environment. Missing variables, duplicate inline keys, and names repeated in both `env` and `secret_env` are rejected.

The backend uses `secret_env` to read Kubernetes Secrets, for example:

```yaml
secret_env:
  POSTGRES_PASSWORD:
    name: platform-bootstrap-secrets
    key: POSTGRES_PASSWORD
```

The topology's `secrets` section maps each Secret key to a host variable from `.env`. `env_from` imports every key from a declared Secret. Keep credentials out of ordinary environment entries and chart values, which enter generated Git snapshots. Secret references do not encrypt `.env` or other local files.

The backend also declares `external_secret` to read `deployguard/python-backend` through the `vault-backend` SecretStore. The SecretStore tells External Secrets Operator (ESO) how to connect to Vault; the generated ExternalSecret specifies which Vault KV v2 path to copy into a Kubernetes Secret. Vault support is optional; an already initialized Vault does not need a seeder.

Use a namespace-qualified Vault address, as the scenario does, because ESO runs in `external-secrets`. On sync, DeployGuard refreshes managed ExternalSecrets and restarts selected Deployments or StatefulSets when referenced Secret versions change. Run sync after changing a Vault value to update running containers.

## Adapt the pattern to your application

Supply your source and a Dockerfile, then declare the service, its dependencies, and its settings. The [topology schema](../platform/config/topology.schema.json) lists supported fields.

| Setting | Behavior |
| --- | --- |
| `build_path` | Directory relative to the topology; defaults to `services/<name>` or `tests/<name>` for tests |
| `type` | `webservice` by default; also `worker` or `test` |
| `port` / `health_endpoint` | Web container port and HTTP readiness path; defaults are 8000 and `/health` |
| `command` / `args` | Arrays overriding the image entry point and arguments; shell operators need an explicit shell |
| `resources` | Kubernetes CPU, memory, and ephemeral-storage requests and limits |

Names must be unique lowercase DNS labels of at most 40 characters. Web services must listen on all interfaces and return a successful health response.

The built-in charts run one replica with one container. Use a [dependency chart](dependencies.md) for other workload shapes or advanced networking. Application fields do not configure prebuilt images, remote source checkout, custom Dockerfile names, build arguments, or build secrets.

After source or configuration edits, run `sync` again. See [initialization](seeds.md) for migrations and [tests](tests.md) for test Jobs.
