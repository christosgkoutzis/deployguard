# Initialize data and run migrations

The test scenario uses two forms of initialization: a shared seed prepares Vault, and a service command prepares the backend's database. Both run as Kubernetes Jobs.

## Prepare a shared dependency

The `vault-seeder` entry in [deployguard.yaml](../deployguard.yaml) is:

```yaml
- name: vault-seeder
  build_path: seeds/vault-seeder
  files: seeds/vault-seeder
  command: [python, /seeds/seed_vault.py]
  depends_on: [vault]
  env_from: [platform-bootstrap-secrets]
```

Its [Dockerfile](../seeds/vault-seeder/Dockerfile) supplies the runtime libraries. Its [seed script](../seeds/vault-seeder/seed_vault.py) reads local credentials and writes the application settings into Vault KV v2. The SecretStore depends on this seed, so applications read their settings afterwards.

After [deploying the scenario](get-started.md), inspect the seed's output with:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard logs -l app=vault-seeder --tail=30
```

The log includes `Successfully seeded Vault secrets` for each configured path.

For your own seed, supply either `image` or `build_path` and a `command` array. The `files` directory is mounted at `/seeds`; it must be a flat directory of text files that fits in a ConfigMap. Install required libraries in the image and keep credentials in Secrets.

Unchanged inputs retain the completed seed Job. Changes to its files, configuration, image reference, or declared bootstrap credentials create a new Job. Credential changes can rerun seeds even when used elsewhere in the topology. Seeds must therefore tolerate repeated execution.

## Prepare application data

The backend's `env` includes `INIT_COMMAND=python migrate.py && python seed_db.py`. Its image contains [migrate.py](../services/python-backend/migrate.py), which creates the table and indexes, and [seed_db.py](../services/python-backend/seed_db.py), which inserts sample records only when the table is empty.

You can also use the service field `init_command`; it takes precedence over `INIT_COMMAND`. Commands run through `/bin/sh -c` using the service's image, working directory, environment, secrets, and resource settings.

Initialization runs on each selected deployment sync, after secrets are ready and before the Deployment is applied. It must succeed for the requested deployment revision. If reconciliation completes without running the hook, DeployGuard requests a hook-enabled sync.

Migration scripts must connect to shared storage, as the backend does. Files written only inside the initialization Job do not appear in the service container. Test services keep preparation inside their test program; validation rejects initialization settings on them.

## Failures and repeated execution

ArgoCD can retry an automatic sync up to three times. Initialization commands must be safe to repeat. Successful initialization Jobs are deleted; failed ones remain until another attempt replaces them.

Seed and initialization Jobs use zero Kubernetes retries. Their `timeout` sets the Job deadline, defaulting to `TIMEOUT_SECONDS`; DeployGuard also limits its waits with that setting. Failure or timeout prevents a successful sync.

Next: [run the scenario's tests](tests.md).
