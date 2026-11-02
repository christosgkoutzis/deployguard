# Databases and other dependencies

Use `dependencies` for software supplied by a Helm chart, such as PostgreSQL or RabbitMQ. DeployGuard builds your application images; the dependency chart chooses its own images and Kubernetes resources.

## Add PostgreSQL

Install and bootstrap the cluster using [Get started](get-started.md). Save this complete configuration as `my-app/deployguard.yaml`, creating the directory in your editor if needed:

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
```

`POSTGRES_PASSWORD` comes from the checkout's `.env`, created during installation. Choose its value before the first deployment.

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get service sample-postgres
```

The database is reachable inside the application namespace at `sample-postgres:5432`, with user `postgres` and database `postgres`. The chart uses a persistent volume. It reads its password from the declared Kubernetes Secret.

Adding a database does not configure an application to use it. Your application still needs its database client, connection settings, and schema. The [initialization guide](seeds.md#initialize-shared-data) extends this example with a SQL seed.

Like the [API example](services.md), this uses the configured cluster and environment name. Previously deployed applications remain unless you request `--prune`.

## Use a local chart

This alternative configuration uses the Kafka chart already in the repository. Replace `my-app/deployguard.yaml` with:

```yaml
name: deployguard
dependencies:
  - name: sample-kafka
    path: ../platform/dependencies/confluent-kafka-chart
```

```bash
./scripts/deployguard validate --topology my-app/deployguard.yaml
./scripts/deployguard sync --topology my-app/deployguard.yaml
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get service sample-kafka
```

The chart exposes `sample-kafka:9092` inside the namespace. It runs one Kafka broker in KRaft mode, with temporary storage. Local chart paths resolve relative to the topology file and must contain `Chart.yaml`.

Use `depends_on` when a chart needs another declared dependency or seed first. Local `file://` subcharts are copied with their parent. Download remote subcharts into the chart's `charts/` directory before syncing; DeployGuard does not run dependency updates in your source directories.

## Configure chart values

A remote dependency needs `repo`, `chart`, and an exact `version`. A local dependency needs `path`. Chart settings come from:

1. `values_file`: a YAML mapping, relative to the topology file.
2. `values`: inline entries replace matching **top-level** keys from that file.
3. `set`: Helm parameters take final precedence.

For example, inline `values.primary` replaces the whole `primary` entry from `values_file`. Include all required fields there; these two mappings are not recursively merged. Settings such as `auth.existingSecret` belong to the dependency chart's API.

For private charts, configure [ArgoCD repository credentials](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/). ArgoCD fetches remote charts; host-side Helm credentials alone do not configure that access.

## Keep passwords in Secrets

Use each chart's Secret reference settings, such as `auth.existingSecret` above. Values in `set`, `values`, files, or source charts enter the generated Git repository. Sync rejects generated values that match declared Secret source values; this does not replace reviewing your configuration for credentials.

On sync, DeployGuard restarts selected Deployments and StatefulSets whose referenced Secret versions changed. Updating a Kubernetes Secret does not change a password already stored inside a database. Follow the chart's credential rotation procedure.

## Dependencies in the demo

The bundled topology supplies PostgreSQL, Redis, Kafka, RabbitMQ, Elasticsearch, Vault, and SeaweedFS. Versions and chart settings are in `deployguard.yaml`.

- Kafka and RabbitMQ use local single-node charts with temporary storage. Kafka uses `kafka:9092`; RabbitMQ uses `rabbitmq:5672`, with management on port 15672.
- SeaweedFS supplies S3-compatible storage at `http://seaweedfs-all-in-one:8333`. The applications use local credentials from `.env`; no AWS account is needed. Its data is lost when its pod is replaced.
- Vault runs in development mode. It is a local secret store, not a production Vault installation.
- PostgreSQL and Redis use persistent volumes.

These tools are demo choices. A custom topology can select other charts or omit them.

## Open the dashboards

After a full demo sync, these default URLs are available:

| Tool | URL | Purpose |
| --- | --- | --- |
| ArgoCD | [argocd.127.0.0.1.nip.io:8080](http://argocd.127.0.0.1.nip.io:8080) | Application status, sync operations, and resource details |
| Dozzle | [dozzle.127.0.0.1.nip.io:8080](http://dozzle.127.0.0.1.nip.io:8080) | Pod logs |
| Kafbat UI | [kafka-ui.127.0.0.1.nip.io:8080](http://kafka-ui.127.0.0.1.nip.io:8080) | Kafka topics and events |

Adjust URLs if you change the domain or ingress port. A fresh focused demo excludes Dozzle and Kafbat UI.

The ArgoCD username is `admin`. Retrieve its initial password with:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

ArgoCD renders application charts with Helm and manages their resources. `helm list` shows bootstrap releases such as ArgoCD and External Secrets Operator, not each deployed application.

Next: [initialize data](seeds.md) or [connect your application](services.md).
