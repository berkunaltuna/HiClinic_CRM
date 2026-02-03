# Minimal CRM (Phase 0 → Phase 1)

This repository contains a **minimal CRM** implemented in **FastAPI + PostgreSQL**, evolving in phases.

## What you have now (Phase 1)

- ✅ Phase 0: API + DB + worker skeleton, `/health` endpoint
- ✅ Phase 1: Auth (JWT), Customers, Deals, Interactions, Follow-ups (with DB migrations)

## Prerequisites

- Docker + Docker Compose

## Run

```bash
docker compose up --build
```

The API will:
1) apply DB migrations (Alembic)
2) start Uvicorn on port `8000`

## Verify

### Health

```bash
curl http://localhost:8000/health
```

### Swagger UI

Open:
- http://localhost:8000/docs

## Phase 1 quickstart (curl)

> Tip: set a token shell variable to avoid repetition.

### 1) Register (returns token)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"ChangeMe123!"}' | \
  python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

echo "$TOKEN"
```

### 2) Create a customer

```bash
curl -s -X POST http://localhost:8000/customers \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Ltd","email":"sales@acme.com","next_follow_up_at":"2026-01-22T09:00:00Z"}'
```

### 3) List customers

```bash
curl -s http://localhost:8000/customers \
  -H "Authorization: Bearer $TOKEN"
```

### 4) Create a deal

```bash
curl -s -X POST http://localhost:8000/customers/1/deals \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"amount":1200,"status":"open"}'
```

### 5) Log an interaction

```bash
curl -s -X POST http://localhost:8000/customers/1/interactions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"call","direction":"outbound","content":"Intro call completed."}'
```

### 6) Follow-ups due on a date

```bash
curl -s "http://localhost:8000/followups?date=2026-01-22" \
  -H "Authorization: Bearer $TOKEN"
```

## Notes

- Passwords are stored hashed (bcrypt via passlib)
- JWT access tokens are signed using `JWT_SECRET_KEY` (set in `docker-compose.yml` for local dev)
- Phase 1 uses UTC date boundaries for follow-up queries (kept simple on purpose)


## Real email sending (SMTP / Gmail app password)

By default the app uses a **fake** provider (no real emails) which is also used in tests/CI.

To send real emails via Gmail SMTP, set:

- `EMAIL_PROVIDER=smtp`
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USE_STARTTLS=true`
- `SMTP_USERNAME=info@yourdomain.com`
- `SMTP_PASSWORD=<gmail app password>`
- `SMTP_FROM_EMAIL=info@yourdomain.com`
- `SMTP_FROM_NAME=<display name>`

**Tip:** keep `SMTP_PASSWORD` out of git. Put it in a local `.env` and load it in docker compose, or pass it as an environment variable at runtime.

Tests always force `EMAIL_PROVIDER=fake`.
