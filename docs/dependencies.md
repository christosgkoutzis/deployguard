# External Dependencies & Ecosystem

This document defines exactly how DeployGuard supports external or platform-provided stateful/stateless dependencies (e.g., PostgreSQL, Kafka, Redis, RabbitMQ) and observability tools (e.g., Kafbat UI, Dozzle) via Kubernetes GitOps and generic Secrets.

## The Core Concept

Instead of containerizing community tools manually in the application directory, DeployGuard leverages ArgoCD to fetch and deploy Helm charts. A dependency can point to a public/private Helm repository, or to the local ephemeral Helm repository served by the orchestration script at `http://host.k3d.internal:8081`.

## Required Assumptions & Constraints

1. **No App Code:** Dependencies deployed via this method cannot have local source code. They are platform dependencies, not DeployGuard application services.
2. **Platform Layer:** Dependencies MUST be declared strictly under the `dependencies:` block in your topology YAML. The platform automatically separates them from local services to prevent the build system from searching for a local `Dockerfile`.
3. **Chart Source:** Dependencies may use remote Helm charts or committed local platform charts. Local charts provided by the platform (like Kafka and RabbitMQ) are located in `platform/dependencies/`.
4. **Init Jobs:** If a dependency requires schema initialization (e.g., a database), the microservice consuming it MUST define an `INIT_COMMAND` using a Seed.

## Usage Example (Secure PostgreSQL)

To provision an external service securely via Kubernetes Secrets, define it in your `deployguard.yaml` like this:

```yaml
dependencies:
  - name: postgres
    repo: https://charts.bitnami.com/bitnami
    chart: postgresql
    version: ""
    secret: 
      name: my-postgres-secret
      key_values:
        - "postgres-password=secretpassword"
    set:
      - "global.postgresql.auth.existingSecret=my-postgres-secret"
      - "auth.existingSecret=my-postgres-secret"
      - "architecture=standalone"
```

## Built-In Local Kafka Design

Kafka is provided by the committed `platform/dependencies/confluent-kafka-chart` chart. It runs a single-node Confluent Kafka broker in KRaft mode with Confluent Platform `8.0.6` / Apache Kafka 4.0.x. It exposes `kafka:9092`, disables Kubernetes service-link environment injection to avoid Confluent startup variable collisions, and uses ephemeral `emptyDir` storage. It is designed for local development and CI validation, not durable production messaging.

## Built-In Local RabbitMQ

DeployGuard utilizes a custom local chart (`platform/dependencies/rabbitmq-instance-chart`) to deploy a lightweight, single-node RabbitMQ broker. Instead of relying on complex third-party operators, it directly deploys the official `rabbitmq:3-management` Docker image as a basic Kubernetes Deployment. This local instance is explicitly configured without persistent volumes (using strictly ephemeral container storage) to prevent state-mismatch loops during CI/CD restarts.

## Platform Ecosystem & Observability

DeployGuard gives you instant access to multiple Web UIs for cluster management and live debugging, without needing terminal commands:

* **ArgoCD Dashboard (GitOps):** Open `http://argocd.127.0.0.1.nip.io:8080`. *(Username: `admin`, get password via `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`)*
* **Dozzle (Live Pod Logs):** Open `http://dozzle.127.0.0.1.nip.io:8080` to view a real-time stream of all active pod logs.
* **Kafbat UI (Kafka Topic & Event Explorer):** Open `http://kafka-ui.127.0.0.1.nip.io:8080` to instantly view live broker metrics, explore topics, and inspect events.