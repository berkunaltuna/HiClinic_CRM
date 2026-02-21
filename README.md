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
## Phase 4: .env + secret management

**Do not commit real secrets to GitHub.** From Phase 4 onwards, Docker Compose loads configuration from a local `.env` file.

1) Create your local env file:

```bash
cp .env.example .env
```

2) Edit `.env` and set at least:

- `JWT_SECRET_KEY` (use a strong random string)
- `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` (if you are using SMTP)
- `ADMIN_EMAILS` (comma-separated or a single email)

3) Start the stack:

```bash
docker compose up -d --build
```

### Why you should not commit SMTP passwords

If you commit an SMTP/app password into git, anyone with repo access (or any leaked copy) can send emails as your company address. Treat it like a bank PIN:
- keep it in `.env` locally
- for CI (GitHub Actions), store it as a GitHub Secret and pass it as an env var during the workflow run


## Phase 4A (Twilio WhatsApp) quick test

1) Put your Twilio credentials in `.env` (do **not** commit real secrets):

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM` (e.g. `whatsapp:+14155238886` for sandbox)
- `DEFAULT_COUNTRY_CODE` (default `+44`)

2) Start the stack:

```bash
docker compose up --build
```

3) Create an outbound message (queued). The worker will pick it up and send:

```bash
curl -s -X POST http://localhost:8000/outbound-messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"<CUSTOMER_UUID>","channel":"whatsapp","body":"Hello from HiClinic CRM"}'
```

4) Check status:

```bash
curl -s http://localhost:8000/outbound-messages \
  -H "Authorization: Bearer $TOKEN"
```


## Phase 4B: inbound WhatsApp → CRM lead

This phase adds a Twilio webhook endpoint that:

- creates a **Customer** automatically when an unknown WhatsApp number messages you ("lead")
- stores the message as an **Interaction** (inbound)

Endpoint:

- `POST /webhooks/twilio/whatsapp`

### Local dev note

Twilio can only call your webhook if it can reach your machine (public URL). For local testing you typically use one of:

- `ngrok http 8000`
- `cloudflared tunnel --url http://localhost:8000`

Then set your Twilio WhatsApp webhook to:

- `https://<your-public-url>/webhooks/twilio/whatsapp`


## Phase 5A: Inbox API + minimal UI

Phase 5 adds an **operator inbox** on top of the backend, plus a minimal Next.js frontend.

After starting the stack:

- API docs: `http://localhost:8000/docs`
- Frontend UI: `http://localhost:3000`

The frontend stores the JWT in browser `localStorage`.

### Inbox endpoints

- `GET /inbox/customers?bucket=followup_due|open|waiting|closed&tag=...&stage=...&q=...`
- `GET /inbox/customers/{customer_id}/thread`
- `POST /inbox/customers/{customer_id}/stage`
- `POST /inbox/customers/{customer_id}/followup`
- `POST /inbox/customers/{customer_id}/tags/add`
- `POST /inbox/customers/{customer_id}/tags/remove`
- `POST /inbox/customers/{customer_id}/send-text`
- `POST /inbox/customers/{customer_id}/send-template`


## Phase 5B: Outcomes + Analytics

Record business outcomes:

- `POST /outcomes` with types: `consult_booked`, `deposit_paid`, `treatment_done`, `lost`

Analytics endpoints:

- `GET /analytics/summary`
- `GET /analytics/leads-by-day`
- `GET /analytics/templates`

### Optional: webhook signature validation

By default, signature validation is **OFF** to keep local dev easy.

To enable validation (recommended in production):

- `TWILIO_VALIDATE_SIGNATURE=true`
- `TWILIO_WEBHOOK_BASE_URL=https://<your-public-url>`


## Phase 4C: workflow automation (auto-replies, delayed follow-ups)

This phase adds **Workflows**: simple automation rules that listen for events and enqueue actions.

Current trigger implemented:

- `message.received` (fired by the Twilio WhatsApp webhook)

### New in 4B/4C (this repo)

- **Customer stage**: `customers.stage` (default: `new`)
- **Tags**: `tags` + `customer_tags` (owner-scoped)
- **Auto-tagging on inbound**: always adds `whatsapp`; adds `new_lead` when a customer is auto-created
- **Optional keyword tagging**: set `KEYWORD_TAGS_JSON` to map keywords to tags
- **Cancellable scheduled messages**: outbound messages can set `cancel_on_inbound=true` and will be cancelled when the lead replies

### Workflow actions supported

Actions are stored as JSON array in `workflows.actions`:

- `send_template` (existing)
- `send_text` (existing)
- `add_tag` (new)
- `set_stage` (new)
- `set_follow_up` (new; sets `customers.next_follow_up_at`)

Both `send_template` and `send_text` support:

- `delay_minutes` (schedule)
- `cancel_on_inbound` (auto-cancel on reply)

### Example workflow (auto-reply + tag + stage)

```json
{
  "name": "Welcome new WhatsApp lead",
  "trigger_event": "message.received",
  "is_enabled": true,
  "conditions": {"channel": "whatsapp", "is_new_customer": true},
  "actions": [
    {"type": "add_tag", "tag": "auto_replied"},
    {"type": "set_stage", "stage": "contacted"},
    {"type": "send_text", "body": "Thanks! We'll be in touch.", "delay_minutes": 60, "cancel_on_inbound": true}
  ]
}
```

### Test it (Pytest)

Tests require a **test database**.

1) Create a test DB in Postgres (example):

```bash
createdb crm_test
```

2) Run tests with `DATABASE_URL` containing the word `test`:

```bash
cd api
export DATABASE_URL="postgresql+psycopg://crm:crm@localhost:5432/crm_test"
pytest -q
```

The `test_phase4b4c.py` test covers:

- inbound WhatsApp → auto-create customer
- auto-tags (`whatsapp`, `new_lead`) + keyword tag
- workflow actions (`add_tag`, `set_stage`, `send_text` delayed)
- `cancel_on_inbound` cancelling a queued message when the lead replies

### Create a simple auto-reply workflow (Swagger UI)

1) Open Swagger:

- http://localhost:8000/docs

2) Authorize (JWT):

- register/login, copy `access_token`
- click **Authorize** → paste: `Bearer <token>`

3) Create a workflow:

`POST /workflows`

Example body (auto-reply only for new customers):

```json
{
  "name": "Auto-reply to new WhatsApp leads",
  "trigger_event": "message.received",
  "is_enabled": true,
  "conditions": {
    "channel": "whatsapp",
    "is_new_customer": true
  },
  "actions": [
    {
      "type": "send_text",
      "body": "Thanks for messaging HiClinIQ. A coordinator will reply shortly."
    }
  ]
}
```

### Delayed follow-up example

Use `delay_minutes` on an action:

```json
{
  "type": "send_text",
  "body": "Just checking in — do you want to book a consultation?",
  "delay_minutes": 60
}
```

The worker will only send queued outbound messages when `not_before_at` is in the past.
```
