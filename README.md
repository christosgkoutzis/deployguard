<h1 align="center">Welcome to DeployGuard 🛡️</h1>

<h3 align="center">A declarative, GitOps-driven local Kubernetes environment for microservices! 🚀</h3>

<p align="center">
    <img src="https://img.shields.io/badge/Kubernetes-326ce5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="kubernetes">
    <img src="https://img.shields.io/badge/ArgoCD-ef7b4d?style=for-the-badge&logo=argo&logoColor=white" alt="argocd">
    <img src="https://img.shields.io/badge/Helm-0f1689?style=for-the-badge&logo=helm&logoColor=white" alt="helm">
    <img src="https://img.shields.io/badge/Docker-2496ed?style=for-the-badge&logo=docker&logoColor=white" alt="docker">
    <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="python">
</p>

## Inspiration

Local development for complex, event-driven microservices is traditionally painful. Developers struggle with heavy docker-compose files, mismatched configurations, and manual dependency setups. DeployGuard brings familiar Kubernetes and platform engineering workflows to a developer's machine.

## Purpose

DeployGuard is a standalone local development tool for building and running microservices, dependencies, mocks, seeds, and integration tests. A declarative `deployguard.yaml` describes the environment. DeployGuard combines k3d, Skaffold, Helm, and ArgoCD without depending on any company's repositories or platform.

## Features

- **Declarative Topology:** Validate entity names, build paths, secret references, and the complete dependency graph before deployment.
- **Skaffold Builds:** Build selected local Docker contexts, reuse its build cache, and deploy the resulting image references through k3d.
- **GitOps via ArgoCD:** Generate a separate local Git repository and serve immutable snapshots through Nginx. ArgoCD owns workload deployment and dependency ordering.
- **Dependency Graph & Focus Mode:** Use `--focus <entity>` to select its prerequisites. Existing unselected applications remain until you explicitly request `--prune`.
- **Mocks, Seeds & Secrets:** Use WireMock, explicit initialization Jobs, Kubernetes Secret references, and optional Vault bindings through External Secrets Operator.
- **Integrated Test Runner:** Register suspended test Jobs and execute them explicitly, with live logs and authoritative Kubernetes Job results.

## Usage

👉 **[Read the Full Get Started Guide](docs/get-started.md)**

From the repository root, prepare the local tooling:

```bash
./scripts/deployguard install
```

Set your credentials in `.env`, define your topology, and run:

1. Define and validate your topology with `./scripts/deployguard validate`.
2. Run `./scripts/deployguard setup` to create the local k3d cluster.
3. Run `./scripts/deployguard bootstrap` to install ArgoCD and any required secret operator.
4. Run `./scripts/deployguard sync` to build, deploy, and verify the selected environment.
5. Run `./scripts/deployguard test <test-name>` to execute an integration suite.

## Demo / Test Scenario

DeployGuard includes a local demo with a gateway, backend, workers, databases, messaging, mocks, and integration tests.

👉 **[Explore the Test Scenario](docs/test-scenario.md)**

The demo is an example topology. It does not define which technologies your own services must use. To start your own topology, `./scripts/deployguard clear-scenario` moves known demo assets into a recoverable backup; replace `deployguard.yaml` before syncing again.

## Documentation (Entities)

- 📦 **[Services & Workers](docs/services.md)**: Application eligibility, custom paths, environment variables, and secret bindings.
- 🐘 **[Dependencies](docs/dependencies.md)**: Remote Helm charts, local charts, and observability tools.
- 🤡 **[Mock Services](docs/mocks.md)**: WireMock mappings and dependency declarations.
- 🌱 **[Seeds](docs/seeds.md)**: Platform initialization and service migrations.
- 🧪 **[Tests](docs/tests.md)**: Verification, explicit test execution, and CI coverage.

CI checks the documented behavior, the full demo, focused deployment, and a separate generic fixture. A passing run establishes that those checks passed on the tested toolchain; it cannot guarantee every possible application or host configuration.

## License

This project is under the [MIT License](LICENSE).
