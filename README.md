<h1 align="center">Welcome to DeployGuard 🛡️</h1>

<h3 align="center">A local Kubernetes GitOps lab for microservice integration testing and platform experimentation.</h3>

<p align="center">
    <img src="https://img.shields.io/badge/Kubernetes-326ce5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="kubernetes">
    <img src="https://img.shields.io/badge/ArgoCD-ef7b4d?style=for-the-badge&logo=argo&logoColor=white" alt="argocd">
    <img src="https://img.shields.io/badge/Helm-0f1689?style=for-the-badge&logo=helm&logoColor=white" alt="helm">
    <img src="https://img.shields.io/badge/Docker-2496ed?style=for-the-badge&logo=docker&logoColor=white" alt="docker">
    <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="python">
</p>

DeployGuard builds and runs local Kubernetes environments containing application services, background workers, dependencies deployed from Helm charts, HTTP mocks, initialization jobs, and integration tests. Use it to validate service interactions and explore GitOps deployment, dependency ordering, initialization, and secrets management.

A **topology** is a YAML file describing the services, dependencies, configuration, and startup relationships of an environment. The included topology is `deployguard.yaml`. Run `sync` to build and deploy it, then run a test suite inside the cluster. You supply the application source, Dockerfiles, configuration, and test data.

## What it does

- Builds local application images with Skaffold and loads them into a k3d cluster.
- Deploys services, workers, databases, HTTP mocks, and initialization Jobs in the order declared by `depends_on`.
- Uses Helm charts for Kubernetes resources and ArgoCD to keep them matched to the deployed configuration.
- Selects a service or test and its prerequisites with `--focus`. Other deployed applications stay until you explicitly request `--prune`.
- Supplies Kubernetes Secrets directly, with optional Vault and External Secrets Operator support.
- Runs tests as Kubernetes Jobs. The test command fails if its Job fails, disappears, or times out.

**GitOps** means keeping running resources matched to configuration recorded in Git. DeployGuard generates that configuration in a separate local Git repository served by Nginx; ArgoCD applies it. Your application repository is not committed or pushed.

## Run the included test scenario

You need Docker running and Python 3.11 or newer. Check the [prerequisites and installation guide](docs/get-started.md) before starting.

From the repository root:

```bash
./scripts/deployguard install
```

Installation creates `.env`. Review its local credentials, then run:

```bash
./scripts/deployguard validate
./scripts/deployguard setup
./scripts/deployguard bootstrap
./scripts/deployguard sync
./scripts/deployguard test e2e-tests
```

Open [the gateway](http://ruby-gateway.127.0.0.1.nip.io:8080/). Write a greeting, read its approval status, search for it, and generate a CSV report. See the [test scenario](docs/test-scenario.md), including how to retrieve the report from inside the cluster.

The full test scenario includes PostgreSQL, Redis, Kafka, RabbitMQ, Elasticsearch, Vault, and S3-compatible storage. It also includes a Kafka UI and a pod log viewer. These components need Docker memory and disk; they are not all required by custom topologies.

## Where it fits

Use DeployGuard for prepared integration environments and for learning how Kubernetes, Helm, ArgoCD, initialization, and secrets work together.

Code changes need another `sync`. There is no file watcher, live source synchronization, or debugger setup. Built-in application charts support single-container web services, workers, and test Jobs. Other Kubernetes shapes need a dependency chart.

DeployGuard runs locally. It does not discover dependencies, import Compose files, or configure an application's authentication and data for you.

## Guides

- 🚀 **[Get started](docs/get-started.md)**: Install tools and run the test scenario.
- ⚙️ **[How deployment works](docs/get-started.md#how-deployment-works)**: Components, Git snapshots, and deployment flow.
- 🔎 **[Test scenario](docs/test-scenario.md)**: Understand the request flow and inspect the running environment.
- 📦 **[Services & Workers](docs/services.md)**: Application configuration, build paths, environment variables, and secrets.
- 🐘 **[Dependencies](docs/dependencies.md)**: Databases, remote and local Helm charts, and dashboards.
- 🤡 **[Mocks](docs/mocks.md)**: WireMock responses and service dependencies.
- 🌱 **[Initialization](docs/seeds.md)**: Shared seeds and application migrations.
- 🧪 **[Tests](docs/tests.md)**: Test suites, deployment verification, and CI coverage.

CI runs static and unit checks, the test scenario's integration tests, and deployment lifecycle checks on a separate sample environment. Coverage and platform limits are described in the tests guide.

## License

[MIT](LICENSE).
