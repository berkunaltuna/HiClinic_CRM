# Minimal CRM (Phase 0)

This repository implements **Phase 0** from the requirements:
- A runnable local stack via Docker Compose
- API service with `GET /health`
- Postgres database service
- Worker service stub (prints heartbeat)

## Prerequisites
- Docker + Docker Compose

## Run locally

```bash
cd minimal-crm
docker compose up --build
```

## Verify

- API health:

```bash
curl http://localhost:8000/health
```

Expected response (example):

```json
{
  "status": "ok",
  "service": "api",
  "version": "0.0.1"
}
```

## What is *not* included yet (by design)
Phase 0 intentionally does **not** include:
- DB schema/migrations
- Authentication
- Any CRM entities (customers/deals/interactions)
- Job queue (worker is only a stub)

Those start in Phase 1+.
