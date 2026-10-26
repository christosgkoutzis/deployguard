# Initialization & Data Seeding

DeployGuard supports explicit platform seeds and service initialization hooks. Both run inside Kubernetes and participate in ArgoCD dependency ordering.

## 1. Platform Seeds (Infrastructure State)

Use `seeds` for initializing shared dependencies, such as populating Vault, creating Kafka topics, or configuring RabbitMQ vhosts. Each seed declares its prerequisites, runtime, files, and credentials.

```yaml
seeds:
  - name: prepare-data
    image: python:3.11-slim
    files: seeds/prepare-data
    command: [python, /seeds/prepare.py]
    depends_on: [postgres]
    env_from: [database-credentials]
```

Declare the referenced dependency and Secret in the same topology. The files directory resolves relative to the topology. Group each seed under `seeds/<name>/` and set `files` explicitly; omitting it uses `seeds`. Use a flat directory of text files, packaged into a ConfigMap mounted at `/seeds`. Keep its size within Kubernetes ConfigMap limits and keep credentials out of file content.

Supply either `image` or `build_path`, with a Dockerfile at a custom build path. Install libraries in the runtime image instead of downloading them when the Job starts. The demo's `vault-seeder` keeps its Dockerfile, Python dependencies, and seed script together in `seeds/vault-seeder/`.

Job names include a hash of generated configuration, files, the image reference, and declared bootstrap credentials. Unchanged inputs retain the completed Job; changed inputs create a new Job whose successful completion gates dependents. Current credential hashing includes all declared bootstrap Secrets. Make seed scripts idempotent because changed credentials, rebuilt runtimes, or recreating the cluster can trigger initialization again.

## 2. Service Initialization (Application Data)

Keep migrations and application seed scripts in the web service or worker build context so they are included in its image. Declare an `init_command` or `INIT_COMMAND` env entry; `init_command` takes precedence when both are set. Test programs handle preparation themselves instead of using initialization hooks.

```yaml
services:
  - name: python-backend
    depends_on: [postgres, vault-backend]
    init_command: python migrate.py && python seed_db.py
```

Initialization uses an ArgoCD `Sync` hook in wave 1, after any ExternalSecret in wave 0 and before the Deployment in wave 2. It uses the service image, environment, Secret references, and resources. Commands run through `/bin/sh -c` in the image's working directory.

Hooks run on each deployment sync for the selected service. Success requires ArgoCD to report that service's initialization Job as succeeded for the recorded deployment revision. If reconciliation completes without a hook result, DeployGuard requests a full hook-enabled sync; missing or unsuccessful initialization results prevent success. ArgoCD retries automatic synchronizations up to three times; DeployGuard waits for the result within `TIMEOUT_SECONDS`. Successful hooks are removed; failed hooks remain until a subsequent attempt replaces them, including an automatic retry. Images using initialization commands need a shell. Commands must be safe to repeat; applications should coordinate concurrent migrations when needed.

## Execution and Failures

Jobs use `backoffLimit: 0` and an active deadline. An entity's `timeout` overrides its Job deadline; `TIMEOUT_SECONDS` controls default command waits. Failed seeds and initialization hooks prevent successful deployment. Tests execute separately through the [test command](tests.md).
