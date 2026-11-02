# DeployGuard

A local Kubernetes GitOps lab for microservice integration testing and platform experimentation.

DeployGuard builds and runs services and their dependencies on your machine. For example, you can test an API that writes to a database, sends a message to a worker, and calls a mocked HTTP API.

Describe the environment in `deployguard.yaml`, run `sync` to build and deploy it, then run a test suite inside the cluster. You supply the application source, Dockerfiles, configuration, and test data.

## What it does

- Builds local application images with Skaffold and loads them into a k3d cluster.
- Deploys services, workers, databases, HTTP mocks, and initialization Jobs in the order declared by `depends_on`.
- Uses Helm charts for Kubernetes resources and ArgoCD to keep them matched to the deployed configuration.
- Selects a service or test and its prerequisites with `--focus`. Other deployed applications stay until you explicitly request `--prune`.
- Supplies Kubernetes Secrets directly, with optional Vault and External Secrets Operator support.
- Runs tests as Kubernetes Jobs. The test command fails if its Job fails, disappears, or times out.

Each sync creates a separate local Git snapshot for ArgoCD, served by Nginx. DeployGuard does not commit or push your application repository.

## Run the included demo

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

Open [the demo gateway](http://ruby-gateway.127.0.0.1.nip.io:8080/). Write a greeting, read its approval status, search for it, and generate a CSV report. See the [demo walkthrough](docs/test-scenario.md), including how to retrieve the report from inside the cluster.

The full demo includes PostgreSQL, Redis, Kafka, RabbitMQ, Elasticsearch, Vault, and S3-compatible storage. It also includes a Kafka UI and a pod log viewer. These components need Docker memory and disk; they are not all required by custom topologies.

## Where it fits

Use DeployGuard for prepared integration environments and for learning how Kubernetes, Helm, ArgoCD, initialization, and secrets work together.

Code changes need another `sync`. There is no file watcher, live source synchronization, or debugger setup. Built-in application charts support single-container web services, workers, and test Jobs. Other Kubernetes shapes need a dependency chart.

DeployGuard runs locally. It does not discover dependencies, import Compose files, or configure an application's authentication and data for you.

## Guides

| Task | Guide |
| --- | --- |
| Install tools and run the demo | [Get started](docs/get-started.md) |
| Understand and use the demo | [Demo walkthrough](docs/test-scenario.md) |
| Run your own API or worker | [Services](docs/services.md) |
| Add a database or Helm chart | [Dependencies](docs/dependencies.md) |
| Replace an HTTP API with a mock | [Mocks](docs/mocks.md) |
| Initialize shared data or run migrations | [Initialization](docs/seeds.md) |
| Write tests and understand CI | [Tests](docs/tests.md) |

CI runs static and unit checks, the demo's integration tests, and deployment lifecycle checks on a separate sample environment. Coverage and platform limits are described in the tests guide.

## License

[MIT](LICENSE).
