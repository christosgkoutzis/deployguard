# Mock an HTTP API

The test scenario uses WireMock instead of a real external API. Its files are in [mocks/external-api-mock](../mocks/external-api-mock):

| File | Request | Response |
| --- | --- | --- |
| [greeting.json](../mocks/external-api-mock/greeting.json) | `GET /api/greeting` | A greeting containing `Hello from the mocked API!` |
| [validate.json](../mocks/external-api-mock/validate.json) | `POST /api/validate` | `{"result":"Approved"}` |

The backend requests the greeting. The Kafka worker calls the validation endpoint before approving an event.

## Request the mock

After [setup and bootstrap](get-started.md), deploy the backend and its prerequisites:

```bash
./scripts/deployguard sync --focus python-backend
curl --fail http://external-api-mock.127.0.0.1.nip.io:8080/api/greeting
curl --fail http://python-backend.127.0.0.1.nip.io:8080/mock-greeting
```

Both requests return the mocked greeting. Inside the cluster, the mock is available at `external-api-mock-service:80`.

## Configure mappings

The topology lists `external-api-mock` under `mocks`. Services that need it declare it in `depends_on` so focused deployments include it.

Each mock needs at least one JSON mapping in `mocks/<name>/`, relative to the topology file. A mapping contains `request` and `response` objects, as the linked files show. WireMock checks the detailed mapping rules when it starts.

After editing a mapping, sync again. Changed mappings restart WireMock; unchanged mappings retain its pod. The scenario's tests expect the committed responses, so restore them before rerunning that suite.

Mappings are stored in a ConfigMap. Keep them small; nested response-file directories are not supported by the built-in chart.

WireMock handles HTTP, including REST and SOAP. Use [dependency charts](dependencies.md) for databases or message brokers.
