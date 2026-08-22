# Initialization & Data Seeding

DeployGuard strictly separates Infrastructure State from Application Data. It provides two distinct seeding mechanisms to ensure a clean Separation of Concerns across your local environment.

## 1. Platform Seeds (Infrastructure State)

Use platform seeds for initializing cluster-level dependencies. Examples include seeding HashiCorp Vault secrets, creating complex Kafka topics, or configuring RabbitMQ vhosts.

*   **Location:** Place your scripts in the root `seeds/` directory (e.g., `seeds/seed_vault.py`).
*   **How it works:** The orchestrator dynamically packages the contents of this directory into a global Kubernetes `ConfigMap` during the deployment phase.
*   **Execution:** These files are automatically mounted as read-only inside your service's initialization container at the `/seeds/` path.

## 2. Service Seeds (Application Data)

Use service seeds for inserting dummy data, creating default users, or running database schema migrations specific to a single microservice.

*   **Location:** Place your scripts directly inside your microservice's directory, e.g., `services/<service-name>/` (e.g., `services/python-backend/seed_db.py`).
*   **How it works:** These files are naturally built into your service's Docker image during the build phase.
*   **Execution:** They are executed directly from your application's working directory.

## How to Trigger Them (The Chain)

Developers can trigger both Platform and Service seeds sequentially by defining an `INIT_COMMAND` environment variable inside the `deployguard.yaml`. 

When this command is present, DeployGuard automatically wraps it in an ephemeral Kubernetes `Job` using Helm hooks (`pre-install`, `pre-upgrade`). This ensures that the initialization script completely finishes before the main application pods are allowed to start.

**Example `deployguard.yaml` configuration:**
```yaml
services:
  - name: python-backend
    depends_on:
      - postgres
      - vault
    env:
      # 1. Platform Seed (Vault) -> 2. App Migration (Tables) -> 3. App Seed (Dummy Data)
      - INIT_COMMAND="python /seeds/seed_vault.py && python migrate.py && python seed_db.py"
```