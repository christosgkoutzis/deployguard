# Databases and other dependencies

A dependency is software supplied by a Helm chart. The [test scenario topology](../deployguard.yaml) contains remote charts for PostgreSQL, Redis, Vault, and SeaweedFS, plus local charts for Kafka and RabbitMQ.

## Read a remote chart declaration

The scenario's PostgreSQL entry includes:

```yaml
- name: postgres
  repo: https://charts.bitnami.com/bitnami
  chart: postgresql
  version: "18.8.13"
```

Its `set` entries choose standalone mode, a persistent volume, and the existing `platform-bootstrap-secrets` Secret. Read the complete entry in `deployguard.yaml`; the excerpt above is not a standalone topology.

After [setup and bootstrap](get-started.md), deploy this dependency and inspect its Service:

```bash
./scripts/deployguard sync --focus postgres
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get service postgres
```

Application pods connect to `postgres:5432` with user `postgres`, database `postgres`, and the password configured in `.env`. Adding a database does not create your application's schema; the backend's [initialization](seeds.md) does that.

Remote charts need an exact `version`. ArgoCD fetches them; configure private chart access through [ArgoCD repository credentials](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/).

## Read a local chart declaration

Kafka uses the committed chart at [platform/dependencies/confluent-kafka-chart](../platform/dependencies/confluent-kafka-chart):

```yaml
- name: kafka
  path: platform/dependencies/confluent-kafka-chart
```

Paths resolve relative to the topology file and must contain `Chart.yaml`. The full entry also sets its image version and heap size. Use `depends_on` when a chart needs another dependency or seed first.

Local `file://` subcharts are copied with their parent. Vendor remote subcharts into `charts/` before syncing; DeployGuard does not run dependency updates in your source directories.

## Values and credentials

Chart values are applied in this order:

1. `values_file`: a YAML mapping, relative to the topology.
2. `values`: inline entries replace matching **top-level** keys from that file.
3. `set`: Helm parameters take final precedence.

For example, inline `values.primary` replaces the whole `primary` entry from `values_file`. The two mappings are not recursively merged. Individual settings, such as `auth.existingSecret`, belong to the chart's API.

Use chart-native Secret references for credentials. Generated values enter Git history; sync rejects values matching declared Secret sources. Review source charts and files for credentials too.

Sync restarts selected Deployment and StatefulSet consumers when referenced Secret versions change. Changing a Secret does not change a password already stored inside a database; follow the chart's rotation procedure.

## Storage and endpoints in the test scenario

| Component | Address inside the application namespace | Storage |
| --- | --- | --- |
| PostgreSQL | `postgres:5432` | Persistent volume |
| Redis | `redis-master:6379` | Persistent volume |
| Kafka | `kafka:9092` | Temporary pod storage |
| RabbitMQ | `rabbitmq:5672` | Temporary pod storage |
| SeaweedFS S3 API | `http://seaweedfs-all-in-one:8333` | Temporary pod storage |

SeaweedFS uses the local S3 credentials in `.env`; no AWS account is needed. Vault runs in development mode. These are local test configurations; choose charts and persistence appropriate to your own environment.

## Open the dashboards

After a full scenario sync, these default URLs are available:

| Tool | URL | Purpose |
| --- | --- | --- |
| ArgoCD | [argocd.127.0.0.1.nip.io:8080](http://argocd.127.0.0.1.nip.io:8080) | Application status and resource details |
| Dozzle | [dozzle.127.0.0.1.nip.io:8080](http://dozzle.127.0.0.1.nip.io:8080) | Pod logs |
| Kafbat UI | [kafka-ui.127.0.0.1.nip.io:8080](http://kafka-ui.127.0.0.1.nip.io:8080) | Kafka topics and events |

Adjust URLs for your configured domain and ingress port. A fresh `--focus e2e-tests` deployment excludes Dozzle and Kafbat UI.

The ArgoCD username is `admin`. Retrieve its initial password with:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

ArgoCD renders application charts with Helm and manages their resources. `helm list` shows bootstrap releases, not each application.
