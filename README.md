# Chronos Birthday API

This is a FastAPI service that stores user birthdays and returns countdown messages, packaged with Helm.

The helm chart contains a template for an ephemeral PostgreSQL instance used for e2e testing purposes and local validation. It can be disabled, and it is NOT intended for production usage.

Attached is the [detailed cloud architecture documentation](architecture/architecture.md), along with discussion on tradeoffs about how to best deploy this service (or similar ones) to production on AWS.

---

## Prerequisites

- Docker
- Python 3.11+
- Helm v3+
- kind (Kubernetes in Docker)
- kubectl

---

## Quick Start

### Local Unit Tests
```bash
make unit-tests
```

### Full Local Validation (kind + Helm + E2E)

```bash
make all
```

This target unit tests the birthday application, spins up a local kind cluster, builds the image, deploys the Helm chart, runs curl smoke tests against the port-forwarded service, and cleans up.

---

## API Reference
- `PUT /hello/{username}`: With a `{"dateOfBirth": "YYYY-MM-DD"}` payload, it will store or update the user's birthday. Returns `204 No Content`.
- `GET /hello/{username}`: Returns either birthday greeting or remaining day(s) to birthday. Returns `200 OK` or `404 Not Found`.
- `GET /healthz`: Returns `{"status": "ok"}` along with a `200 OK` if the process is able to respond (purposed for automated probing).
