# External Dependency Eligibility Contract

This document defines exactly how DeployGuard supports external or platform-provided stateful/stateless dependencies (e.g., PostgreSQL, Kafka, Redis, RabbitMQ) and observability tools (e.g., Kafbat UI, Dozzle) via Kubernetes GitOps and generic Secrets.

## The Core Concept
Instead of containerizing community tools manually in the `app/` directory, DeployGuard leverages ArgoCD to fetch and deploy Helm charts. A dependency can point to a public/private Helm repository, or to the local ephemeral Helm repository served by `dev-deploy.sh` at `http://host.k3d.internal:8081`.

## Validation Performed by `scripts/add-dependency.sh`
The script generates a raw ArgoCD Application definition and optionally a Kubernetes Secret for secure credential injection. It enforces:
1. Presence of a valid App Name, Helm Repository URL, and Chart Name.
2. Safe creation of Base64 encoded Kubernetes Secrets using the `--secret` flag.
3. Correct mapping of user-provided `--set` arguments to ArgoCD Helm parameters.

## Required Assumptions & Constraints
1. **No App Code:** Dependencies deployed via this script cannot have local source code in `app/`. They are platform dependencies, not DeployGuard application services.
2. **Chart Source:** Dependencies may use remote Helm charts or committed platform charts that `dev-deploy.sh` packages into the local Helm repository. The Confluent Kafka KRaft chart and the RabbitMQ Instance chart are examples of local platform charts.
3. **Platform Layer:** Dependency names MUST be injected into the deployment lifecycle as `PLATFORM_APPS` in the `dev-deploy.sh` pipeline to prevent the build system from searching for a local Dockerfile.
4. **Init Jobs:** If a dependency requires schema initialization (e.g., a database), the microservice consuming it MUST define an `INIT_COMMAND` in its service environment. The platform wraps this command in a Kubernetes Job with a Helm hook, executing it before the microservice starts.

## Built-In Local Kafka
Kafka is provided by the committed `platform/confluent-kafka-chart` chart. It runs a single-node Confluent Kafka broker in KRaft mode with Confluent Platform `8.0.6` / Apache Kafka 4.0.x, exposes `kafka:9092`, disables Kubernetes service-link environment injection to avoid Confluent startup variable collisions, and uses ephemeral `emptyDir` storage. It is designed for local development and CI validation, not durable production messaging.

## Built-In Local RabbitMQ
DeployGuard utilizes a custom local chart (`platform/rabbitmq-instance-chart`) to deploy a lightweight, single-node RabbitMQ broker. Instead of relying on complex third-party operators, it directly deploys the official `rabbitmq:3-management` Docker image as a basic Kubernetes Deployment. This local instance is explicitly configured without persistent volumes (using strictly ephemeral container storage) to prevent state-mismatch loops during CI/CD restarts.

## Usage Example (Secure PostgreSQL)
To provision an external service securely via K8s Secrets:

```bash
./scripts/add-dependency.sh postgres \
  --repo https://charts.bitnami.com/bitnami \
  --chart postgresql \
  --secret my-postgres-secret auth-password=secretpassword \
  --set auth.existingSecret=my-postgres-secret \
  --set auth.secretKeys.adminPasswordKey=auth-password
```