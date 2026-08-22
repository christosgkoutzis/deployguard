<h1 align="center">Welcome to DeployGuard 🛡️</h1>

<h3 align="center">A declarative, GitOps-driven local Kubernetes environment for microservices! 🚀</h3>

<p align="center">
    <img src="https://img.shields.io/badge/Kubernetes-326ce5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="kubernetes">
    <img src="https://img.shields.io/badge/ArgoCD-ef7b4d?style=for-the-badge&logo=argo&logoColor=white" alt="argocd">
    <img src="https://img.shields.io/badge/Helm-0f1689?style=for-the-badge&logo=helm&logoColor=white" alt="helm">
    <img src="https://img.shields.io/badge/Docker-2496ed?style=for-the-badge&logo=docker&logoColor=white" alt="docker">
    <img src="https://img.shields.io/badge/Bash-4Eaa25?style=for-the-badge&logo=gnu-bash&logoColor=white" alt="bash">
</p>

## Inspiration

Local development for complex, event-driven microservices is traditionally painful. Developers struggle with heavy `docker-compose` files, mismatched production configurations, and manual dependency setups. DeployGuard was inspired by the need to bridge the gap between local environments and production Kubernetes, providing Platform Engineering standards right on the developer's machine.

## Purpose

DeployGuard is an internal developer platform that allows teams to spin up an ephemeral, complete Kubernetes environment locally using `k3d`. It uses a declarative YAML approach (`deployguard.yaml`) and strict GitOps methodologies via ArgoCD. The purpose is to allow developers to focus on writing application code, while DeployGuard handles the scaffolding, dependency resolution, mocking, and E2E testing seamlessly.

## Features

DeployGuard's main features are:

- **Declarative Topology (`deployguard.yaml`)**: Define your entire ecosystem—services, databases, brokers, and mocks—in a single, easy-to-read configuration file.
- **Strict GitOps via ArgoCD**: All deployments are managed by ArgoCD reading from a dynamically generated, ephemeral local Helm repository, ensuring 100% parity with modern deployment practices.
- **Dependency Graph & Focus Mode**: Intelligent dependency resolution (`depends_on`). Use `--focus <service>` to deploy only what you need, saving local CPU and RAM.
- **Built-in Mocks & Seeds**: Native support for WireMock HTTP stubs and database initialization scripts, ensuring strict Separation of Concerns between infrastructure state and application data.
- **Integrated Test Runner**: Spawn ephemeral Kubernetes Jobs to execute E2E and Integration test suites natively inside the cluster's network.

## Usage

In order to try out the project yourself, follow the detailed setup instructions in our getting started guide:

👉 **[Read the Full Get Started Guide](docs/get-started.md)**

A high-level overview of the workflow:
1. Define your `deployguard.yaml`.
2. Run `./scripts/setup.sh` to initialize K3d.
3. Run `./scripts/sync-env.sh` to automatically build, scaffold, and deploy everything via ArgoCD.
4. Verify rollout using `./scripts/verify.sh`.

## Demo / Test Scenario

DeployGuard comes with a fully-featured, built-in Enterprise Event-Driven test scenario.

👉 **[Explore the Test Scenario](docs/test-scenario.md)** 

*(You can easily remove this demo using `./scripts/clear-test-scenario.sh` to start building your own apps!)*

## Documentation (Entities)

DeployGuard treats different architectural components as primary platform entities. Read the specific guides below to understand how each is configured and deployed:

- 📦 **[Services & Workers](docs/services.md)**: Standard HTTP apps and background consumers.
- 🐘 **[Dependencies](docs/dependencies.md)**: External tools (Postgres, Kafka, RabbitMQ) and Platform Observability UI tools.
- 🤡 **[Mock Services](docs/mocks.md)**: Ephemeral WireMock instances.
- 🌱 **[Seeds](docs/seeds.md)**: How data initialization works.
- 🧪 **[Tests](docs/tests.md)**: How the E2E Test runner operates.

## License

This project is under the MIT License.