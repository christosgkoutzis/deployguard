# External Dependencies & Ecosystem

DeployGuard deploys databases, message brokers, and other tools through Helm charts managed by ArgoCD. Message brokers such as Kafka and RabbitMQ pass events or queued tasks between applications. Dependencies use their chart images and are not built from your application source.

## The Core Concept

Declare dependencies under `dependencies`. Choose an exact-version remote chart or a local chart containing `Chart.yaml`. Local paths and values files resolve relative to the topology. ArgoCD fetches remote charts; local charts are copied into generated Git snapshots.

```yaml
secrets:
  - name: database-credentials
    values: {password: DATABASE_PASSWORD}
dependencies:
  - name: postgres
    repo: https://charts.bitnami.com/bitnami
    chart: postgresql
    version: "18.8.13"
    set:
      - fullnameOverride=postgres
      - architecture=standalone
      - auth.existingSecret=database-credentials
      - auth.secretKeys.adminPasswordKey=password
    values:
      primary:
        persistence: {size: 100Mi}
```

Pin exact chart versions; floating versions and ranges are rejected. Dotted and indexed `set` keys use native Helm parameters. A `values_file` supplies a YAML mapping, overlaid with inline `values`: inline entries replace top-level keys rather than recursively merging them. Explicit `set` parameters take final precedence.

## Required Assumptions & Constraints

1. Dependencies deploy charts; DeployGuard does not search them for Dockerfiles.
2. Declare prerequisites with `depends_on`, including other charts or seeds.
3. Local chart `file://` subcharts are copied recursively. Vendor remote subcharts into `charts/` first; sync does not edit source charts or run dependency updates there.
4. Initialize application schemas with service hooks, and shared infrastructure with [platform seeds](seeds.md).
5. Configure private Helm access through ArgoCD's native repository credentials.

Use chart-native `existingSecret` options or Secret references for credentials. A credential in `set`, `values`, or a values file would enter generated Git history and is rejected when it matches a declared secret source. Keep credentials out of source chart files as well. Selected Deployment and StatefulSet consumers are rolled when their Secret versions change. Changing a Secret does not itself change a password stored inside a database; use the dependency's supported credential-update procedure. Third-party settings remain governed by each chart's documented API.

## Built-In Local Kafka Design

The committed `platform/dependencies/confluent-kafka-chart` runs the demo's single-node Confluent Kafka broker in KRaft mode with image version `8.0.6`. It exposes `kafka:9092`, disables service-link environment injection, and uses ephemeral `emptyDir` storage. It provides local development messaging, without production durability.

## Built-In Local RabbitMQ

The committed `platform/dependencies/rabbitmq-instance-chart` runs the demo's single-node `rabbitmq:3-management` instance with ephemeral storage. It reads its password from a Kubernetes Secret and uses native RabbitMQ readiness diagnostics. The Service is `rabbitmq`, exposing AMQP on port 5672 and management on port 15672.

## Demo Object Storage

The demo uses [SeaweedFS Community Edition](https://github.com/seaweedfs/seaweedfs) (Apache 2.0) through its upstream Helm chart. Its all-in-one mode runs storage and the S3 gateway in one pod. The chart version and multi-architecture project image digest are pinned in `deployguard.yaml`.

The S3 endpoint is `http://seaweedfs-all-in-one:8333`. SeaweedFS reads `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` from `platform-bootstrap-secrets` as AWS credential environment variables, which enable authenticated S3 access. Set these values in `.env`; the applications and Vault seed use the same credentials. Data uses `emptyDir` storage and is lost when the pod is replaced. Reports use path-style requests and Signature Version 4 presigned URLs.

These are optional local dependencies. Other topologies can choose different native charts or tools.

## Platform Ecosystem & Observability

With the default configuration and full demo selected:

- **ArgoCD Dashboard:** `http://argocd.127.0.0.1.nip.io:8080`, username admin.
- **Dozzle:** `http://dozzle.127.0.0.1.nip.io:8080`, for live pod logs.
- **Kafbat UI:** `http://kafka-ui.127.0.0.1.nip.io:8080`, for topics and events.

Adjust the domain and port for your settings. Dozzle and Kafbat are ordinary demo dependencies, excluded from a fresh `--focus e2e-tests` deployment.

From the repository root, retrieve the ArgoCD initial password using the installed kubectl:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

ArgoCD uses Helm to render application charts. Helm release listings show bootstrap releases such as ArgoCD and ESO; application workloads are managed through ArgoCD Applications.
