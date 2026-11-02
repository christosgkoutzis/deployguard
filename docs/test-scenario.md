# Demo walkthrough

The bundled demo shows an HTTP request moving through a database, message broker, worker, cache, search index, and CSV export. Use it to explore those connections or as an integration-test example.

Start with [Get started](get-started.md) to install, deploy, and run `e2e-tests`.

## What runs

- **Ruby gateway** calls the Python backend over HTTP and displays its responses.
- **Python backend** stores greetings in PostgreSQL and publishes their IDs to Kafka. Reads check Redis before PostgreSQL.
- **Python worker** consumes Kafka events, asks the HTTP mock to validate them, marks greetings as Approved, and indexes them in Elasticsearch.
- **Report worker** consumes RabbitMQ export tasks and uploads a CSV from PostgreSQL to SeaweedFS's S3-compatible endpoint.
- **Vault and its seed** supply application settings. External Secrets Operator copies those settings into Kubernetes Secrets; the demo applications also support direct Vault reads.
- **WireMock** returns fixed external API responses.
- **Dozzle and Kafbat UI** show pod logs and Kafka topics.

The topology orders these prerequisites. For example, Vault is seeded before application secrets are read, backend initialization runs before its Deployment, and the integration suite depends on both workers.

## Use the gateway

Open [ruby-gateway.127.0.0.1.nip.io:8080](http://ruby-gateway.127.0.0.1.nip.io:8080/) after deployment. Use your configured domain and ingress port if you changed the defaults.

1. The page shows greetings from the backend and the mocked API.
2. Enter a unique greeting and press **Write Custom Event**. The backend stores it and publishes a Kafka event.
3. Press **Read Latest Greeting** after the worker has processed it. Its status becomes **Approved**. Repeated reads within the cache lifetime show **Redis Cache** as the source.
4. Search for the greeting. After indexing, the gateway lists the matching record's ID and status.
5. Press **1. Generate CSV Report (Async)**. The report worker processes the queued task and uploads the report.

Processing and indexing happen asynchronously. An HTTP response or a ready pod does not mean that those steps have finished. A cached greeting can remain visible for up to 15 seconds.

## Retrieve a CSV report

**Download Latest CSV** redirects to a signed S3 URL at `http://seaweedfs-all-in-one:8333`. That hostname is reachable inside Kubernetes, not directly from your host browser. The integration suite downloads and checks the CSV from inside the cluster.

For a copy on your machine, first run the suite so the report is generated and checked:

```bash
./scripts/deployguard test e2e-tests
```

Then download through the backend container, which can resolve the storage hostname:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard exec deployment/python-backend-workload -- python -c '
import json
import sys
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8000/report/download", timeout=10) as response:
    url = json.load(response)["download_url"]
with urlopen(url, timeout=10) as response:
    sys.stdout.buffer.write(response.read())
' > /tmp/deployguard-report.csv
```

Open `/tmp/deployguard-report.csv` in your editor. The command preserves the signed URL's hostname and streams the file to your machine. Changing the hostname in a presigned URL invalidates its signature.

## What the suite proves

`e2e-tests` checks four flows: backend and mock responses, approval of its own written greeting and a cached read, search indexing, and a signed CSV containing that same greeting. It also checks that unsigned object downloads are denied.

Deployment verification covers readiness and initialization separately. On a fresh cluster, `sync --focus e2e-tests` includes this request chain but excludes Dozzle and Kafbat UI. Full sync adds those tools. Switching focus retains other deployed applications unless `--prune` is requested.

## Inspect the environment

Run these commands from the repository root. They use the installed tools and default context and namespace.

### Pods and application status

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard get pods
.local/bin/kubectl --context k3d-control-plane-cluster -n argocd get applications
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard describe deployment/python-backend-workload
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard logs deployment/python-backend-workload --tail=100
```

To open a shell in the backend:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard exec -it deployment/python-backend-workload -- /bin/sh
```

Use `sync` after source edits. Editing a running container is not a persistent source change.

### Databases and queues

Each port-forward command keeps running until stopped. Choose one and use a separate terminal for your database client.

PostgreSQL on localhost port 15432:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard port-forward service/postgres 15432:5432
```

Redis on localhost port 16379:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard port-forward service/redis-master 16379:6379
```

RabbitMQ's AMQP endpoint on localhost port 15673:

```bash
.local/bin/kubectl --context k3d-control-plane-cluster -n deployguard port-forward service/rabbitmq 15673:5672
```

Clients still need the credentials configured in `.env`. See [dependencies](dependencies.md#open-the-dashboards) for dashboard URLs and the ArgoCD login.

### Local Git server

```bash
docker logs deployguard-source-control-plane-cluster
```

This Nginx container serves the generated Git repository to ArgoCD.

## Remove the demo files

Use this when preparing a checkout for your own application:

```bash
./scripts/deployguard clear-scenario
```

The command moves the known demo directories into a backup under `.local/state/scenario-backups/` and prints that location. It includes `services/python-backend`, `services/python-worker`, `services/report-worker`, `services/ruby-gateway`, `tests/e2e-tests`, `mocks/external-api-mock`, `seeds/vault-seeder`, and the two local dependency charts.

Edits inside those directories move with them. Other files, including custom application directories, shared charts, and tool tests, stay in place.

To retain the local Kafka and RabbitMQ charts, use this alternative:

```bash
./scripts/deployguard clear-scenario --skip-dependencies
```

The command leaves the running cluster and `deployguard.yaml` unchanged. Replace the demo topology before the next validation or sync. To restore files, copy them from the printed backup directory to their original paths, taking care not to overwrite newer edits. Removing files does not prune cluster resources.
