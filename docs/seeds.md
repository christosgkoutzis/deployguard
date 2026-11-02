# Initialize data and run migrations

Use a shared seed to prepare a database or another dependency. Use a service's `init_command` for work tied to deploying that application, such as schema migrations.

Both run as Kubernetes Jobs. Commands must be safe to repeat.

## Initialize shared data

This example creates a table and inserts one record in PostgreSQL. Install and bootstrap the cluster using [Get started](get-started.md) first.

Save `my-app/seeds/prepare.sql`:

```sql
CREATE TABLE IF NOT EXISTS sample_messages (
    id integer PRIMARY KEY,
    message text NOT NULL
);
INSERT INTO sample_messages (id, message)
VALUES (1, 'Hello from sample-seed')
ON CONFLICT (id) DO UPDATE SET message = EXCLUDED.message;
SELECT message FROM sample_messages WHERE id = 1;
```

Save this complete configuration as `my-app/deployguard.yaml`. It includes the database from the [dependencies guide](dependencies.md#add-postgresql):

```yaml
name: deployguard
secrets:
  - name: sample-db-credentials
    values: {password: POSTGRES_PASSWORD}
dependencies:
  - name: sample-postgres
    repo: https://charts.bitnami.com/bitnami
    chart: postgresql
    version: "18.8.13"
    set:
      - fullnameOverride=sample-postgres
      - architecture=standalone
      - auth.existingSecret=sample-db-credentials
      - auth.secretKeys.adminPasswordKey=password
    values:
      primary:
        persistence: {size: 100Mi}
seeds:
  - name: sample-seed
    image: postgres:17-alpine
    files: seeds
    depends_on: [sample-postgres]
    secret_env:
      PGPASSWORD: {name: sample-db-credentials, key: password}
    command:
      - psql
      - --host=sample-postgres
      - --username=postgres
      - --dbname=postgres
      - --set=ON_ERROR_STOP=1
      - --file=/seeds/prepare.sql
```

`POSTGRES_PASSWORD` is supplied by the checkout's `.env`. The seed uses the PostgreSQL image for its `psql` client; it connects to the separate database pod.

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml --focus sample-seed
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard logs -l app=sample-seed --tail=20
```

The log includes `Hello from sample-seed`. A successful seed lets its dependents deploy.

Seed files are read from the declared directory and mounted at `/seeds`. Use a flat directory of text files that fits in a ConfigMap. Keep passwords in Secrets.

An unchanged seed retains its completed Job. Changes to its files, configuration, image reference, or declared bootstrap credentials create a new Job. Credential changes can rerun seeds even when the changed credential is used elsewhere in the topology. Recreating the cluster also requires initialization again.

Use either `image` or `build_path` for a seed. For a custom runtime, include required libraries in its Dockerfile. The bundled `seeds/vault-seeder/` is an example.

## Run a command before a service starts

Start with the [small API example](services.md#run-a-small-api). This complete alternative topology checks that its message setting is present before deploying the API:

```yaml
name: deployguard
services:
  - name: sample-api
    build_path: api
    env:
      - MESSAGE=Hello from sample-api
    init_command: >-
      python -c "import os; assert os.environ.get('MESSAGE'), 'MESSAGE must not be empty'"
```

Save it as `my-app/deployguard.yaml`, then run:

```bash
./scripts/deployguard sync --topology my-app/deployguard.yaml --focus sample-api
curl --fail http://sample-api.127.0.0.1.nip.io:8080/greeting
```

The same field can run migration scripts included in your application's image. Those scripts must connect to the shared database; files written only inside the initialization Job do not appear in the service container.

Initialization uses the service's image, environment, Secret references, and resource settings. Commands run through `/bin/sh -c` in the image's working directory, so the image needs a shell.

An `INIT_COMMAND` environment entry is also supported; `init_command` takes precedence. Test Jobs handle their preparation inside the test program or entry point. Validation rejects initialization settings on test services.

## When commands run and fail

Service initialization runs on each selected deployment sync, after its secrets are ready and before its Deployment is applied. DeployGuard requires a successful initialization result for that deployment revision. If ArgoCD completes reconciliation without running the hook, DeployGuard requests a hook-enabled sync.

ArgoCD can retry a failed automatic sync up to three times. Initialization commands may therefore run more than once and must tolerate repeated execution. Successful initialization Jobs are deleted; failed ones remain until another attempt replaces them.

Seed and initialization Jobs use `backoffLimit: 0`. Their `timeout` sets the Job deadline, defaulting to `TIMEOUT_SECONDS`. DeployGuard also limits its waits with `TIMEOUT_SECONDS`. Failure or timeout prevents a successful sync.

Next: [run tests](tests.md).
