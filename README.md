# Enterprise API Integration Platform

A  **working MVP** demonstrating REST API design, API-key authentication, transactional outbox, asynchronous delivery, retry/backoff, request idempotency, signed inbound webhooks, integration monitoring, and automated tests.

## Architecture

```text
Authenticated client --POST /api/customers--> FastAPI
                                             |
                                             v
                                       SQL database
                                       /          \
                                 Customers       Outbox (pending)
                                                     |
                                                     v
                                              Background worker
                                                     |
                                             HTTP POST + retry
                                                     |
                                                     v
                                             Mock partner API

External webhook --HMAC signature--> /api/webhooks/partner --> deduplicated events
```

## Quick start: Docker + PostgreSQL (recommended)

```bash
docker compose up --build
```

Open http://localhost:8000/docs for interactive Swagger UI.

In another terminal:

```bash
curl -X POST http://localhost:8000/api/customers \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-local-key-change-me' \
  -H 'Idempotency-Key: demo-001' \
  -d '{"name":"Alex Morgan","email":"alex@example.com"}'

curl -H 'X-API-Key: dev-local-key-change-me' http://localhost:8000/api/integrations
curl -H 'X-API-Key: dev-local-key-change-me' http://localhost:8000/api/metrics
```

The worker delivers pending jobs to the mock partner. Repeat the first POST with the same idempotency key and payload to verify it does not create a second customer. Change the payload while reusing the key to see HTTP 409.

## Quick start: Local Python + SQLite

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

In a **second** terminal, from the same directory and virtual environment:

```bash
python -m app.worker
```

## Test

```bash
pytest -q
```

## Failure-recovery demonstration

1. Start the API but stop the worker.
2. Create a customer and confirm `/api/integrations` shows `pending`.
3. Set `PARTNER_URL` in the worker environment to a temporarily unavailable URL and start worker; observe `retrying`, attempts and errors.
4. Stop worker; restore `PARTNER_URL` to `http://localhost:8000/mock-partner/customers` (or `http://api:8000/mock-partner/customers` inside Docker); restart worker.
5. Observe `delivered` after retry. Jobs reaching `MAX_ATTEMPTS` remain `failed` and need manual intervention.

## Signed inbound webhook example

```python
import hashlib, hmac, json, requests
payload = json.dumps({'event_id': 'evt-100', 'type': 'customer.updated'}).encode()
signature = hmac.new(b'change-me-in-production', payload, hashlib.sha256).hexdigest()
r = requests.post('http://localhost:8000/api/webhooks/partner', data=payload,
    headers={'X-API-Key': 'dev-local-key-change-me', 'X-Webhook-Signature': signature,
             'Content-Type': 'application/json'})
print(r.status_code, r.json())
```

## Endpoint reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/api/customers` | POST | Create customer and enqueue delivery atomically |
| `/api/customers/{id}` | GET | Customer and sync status |
| `/api/integrations` | GET | Latest 100 delivery jobs |
| `/api/metrics` | GET | Counts by job status |
| `/api/webhooks/partner` | POST | Validate HMAC and deduplicate inbound events |
| `/mock-partner/customers` | POST | Demo-only partner endpoint |
| `/docs` | GET | OpenAPI UI |

## Engineering tradeoffs and next steps

This is an **educational MVP, not production-ready**. It demonstrates important patterns but deliberately keeps the implementation small.

- The worker is **single-instance only**; multiple workers can claim the same job. Production needs atomic job leasing / `FOR UPDATE SKIP LOCKED`, lease expiry, and recovery.
- Delivery is **at least once**, not exactly once. The mock partner deduplicates by event ID. Real partners need their own idempotency guarantees.
- `POST /api/customers` idempotency key lookup and insert may race under simultaneous requests; production should catch unique-constraint conflicts and return the existing result safely.
- Retry uses exponential backoff with a cap but no jitter. Add jitter, circuit breakers, per-partner rate limiting, and dead-letter replay tooling.
- The mock partner endpoint is intentionally unauthenticated. Never expose it in a real deployment.
- Protect production secrets with a secrets manager, use TLS, add OAuth2/JWT or scoped credentials, request validation, rate limiting, structured logs, tracing, metrics, and migrations (Alembic).
- This demo does not provide an actual graphical dashboard; `/api/integrations` and `/api/metrics` are JSON monitoring endpoints.
- Add CI, load tests, multi-tenant isolation, and a real third-party sandbox integration for a stronger portfolio project.




4. Simulate a partner outage and show retry status and recovery.
5. Explain security controls and which safeguards are still needed for production.
