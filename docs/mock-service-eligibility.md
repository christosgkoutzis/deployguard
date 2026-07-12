# Mock Service Eligibility Contract

This document defines exactly how DeployGuard supports local ephemeral mock services using WireMock.

If a mock service meets the requirements below and fails to deploy via the local cluster scripts, it is considered a repository bug.

## Supported Technology Scope

1. **HTTP/HTTPS APIs Only:** The mock service uses WireMock, meaning it can only simulate RESTful or SOAP endpoints over HTTP.
2. **No Stateful/Binary Protocols:** You cannot mock raw databases (e.g., PostgreSQL, MySQL) or message brokers. WireMock strictly intercepts HTTP traffic. 

## Required Mock Location

1. Mock data must live in `platform/mocks/<mock-name>/`.
2. `<mock-name>` must be lowercase, alphanumeric, and hyphen only.

## Required Files

1. At least one valid WireMock `.json` stub mapping file must exist inside `platform/mocks/<mock-name>/`.

## Validation Performed by `scripts/add-mock.sh`

1. Path and naming checks.
2. Directory creation.
3. Scaffolding of a sample JSON endpoint to ensure the directory is not empty.

## Execution Requirements

Mock services are not auto-detected. To inject a mock service into the deployment lifecycle, pass its name to the `MOCK_APP_NAMES` environment variable when running the deployment script:

```bash
MOCK_APP_NAMES=external-api-mock ARGO_APP_NAMES=... ./scripts/dev-deploy.sh