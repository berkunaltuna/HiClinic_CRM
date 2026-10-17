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


## Phase 6: Meta / Facebook Lead Ads webhook

This adds a Meta webhook endpoint that can ingest Facebook Lead Form submissions into the CRM.

### What it does

When Meta posts a `leadgen` event to the API:

- creates or updates a matching **Customer** (dedupe by phone, then email)
- creates an open **Deal** if the customer does not already have one
- records a **Facebook Lead Form submission** interaction
- tags the customer with `facebook` and `facebook_lead`
- stores the raw lead payload in `facebook_lead_events` to prevent duplicate imports

### Endpoints

- `GET /webhooks/meta/facebook` — verification handshake
- `POST /webhooks/meta/facebook` — lead webhook receiver

### Required env vars

Add these to `.env`:

- `FACEBOOK_VERIFY_TOKEN`
- `FACEBOOK_PAGE_ACCESS_TOKEN`
- `FACEBOOK_APP_SECRET`
- `FACEBOOK_GRAPH_API_VERSION`
- `FACEBOOK_DEFAULT_OWNER_USER_ID` (optional)
- `FACEBOOK_VALIDATE_SIGNATURE`

### Meta setup

1. Create a Meta app and add **Webhooks**.
2. Subscribe the **Page** object to the `leadgen` field.
3. Use a public HTTPS callback URL, for example:
   - `https://<your-domain>/webhooks/meta/facebook`
4. Use the same `FACEBOOK_VERIFY_TOKEN` value in Meta and your `.env`.
5. Make sure your page access token has lead retrieval access.

### Local testing

Meta cannot call `localhost` directly. For local testing, expose the API with something like:

```bash
ngrok http 8000
```

Then set the callback URL in Meta to the public HTTPS URL plus:

```text
/webhooks/meta/facebook
```

### Apply the migration

```bash
docker compose exec api alembic upgrade head
```


## Facebook leads: direct Meta webhook + Make fallback

This project supports two compatible Facebook lead ingestion paths:

- Direct Meta webhook: `POST /webhooks/meta/facebook`
- Make.com fallback: `POST /webhooks/make/facebook-lead`

The Make endpoint is intended for scenarios where Meta webhook delivery is difficult to stabilise during setup. It accepts normalised JSON from Make, deduplicates by `lead_id` / `leadgen_id`, creates or updates the customer, opens a deal if needed, logs an interaction, and stores the raw payload in `facebook_lead_events`.

Optional hardening for the Make endpoint:

- Set `MAKE_WEBHOOK_SECRET` in `.env`
- Send the same value from Make in the `X-Make-Secret` header

Suggested Make request body:

```json
{
  "lead_id": "1234567890",
  "page_id": "295777210289573",
  "form_id": "987654321",
  "form_name": "Aesthetics Consultation Form",
  "campaign_id": "111",
  "campaign_name": "TMJ Campaign",
  "adset_id": "222",
  "adset_name": "London Audience",
  "ad_id": "333",
  "ad_name": "TMJ Video 1",
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "phone": "+447700900123",
  "company": "Health Journey",
  "created_time": "2026-09-18T06:35:11.000Z",
  "raw": {}
}
```

`created_time` should be mapped from the Facebook Lead Ads trigger module's **Date created** output field. Without it, the CRM falls back to stamping `created_at` at the moment the webhook is processed, which can put leads out of chronological order if Make delivers them out of submission order (batching, retries, scenario re-runs).

## Google Ads lead form webhook

Scope: this receives submissions from **Google Ads' built-in lead form assets** only (the form Google shows inside the ad). Forms on our own website/WordPress landing pages do not come through here.

- `POST /webhooks/google/ads-lead`

What a submission does:

- Validates `google_key` against `GOOGLE_ADS_WEBHOOK_KEY` before touching the database (403 if missing/wrong; 503 if the env var is unset, so Google keeps retrying until it is configured).
- Deduplicates on Google's `lead_id` (stored as `google:<lead_id>` in `facebook_lead_events`, unique). Replays and concurrent duplicate deliveries record one submission; a failed delivery writes nothing, so Google's retry starts clean.
- Matches an existing customer by phone, then email, across all users when `SHARE_CUSTOMERS_ACROSS_USERS=true` (same matcher as the Excel importer). Otherwise creates a customer in stage **new** with `lead_source=google`.
- Existing customers keep their stage, name, original `lead_source`/campaign attribution and existing deal treatment. The Google submission is recorded separately: a lead event row (`source=google`, `gclid`, `is_test`), an interaction "Google Ads Lead Form submission" whose content holds `lead_id`, `form_id`, `campaign_id`, `adgroup_id`, `creative_id`, `asset_group_id`, `gcl_id`, `lead_stage`, and the answers, plus additive tags (`google`, `google_ads_lead`, treatment tags).
- Field mapping: `FULL_NAME` (or `FIRST_NAME` + `LAST_NAME`), `EMAIL`/`WORK_EMAIL`, `PHONE_NUMBER`/`WORK_PHONE`, `COMPANY_NAME`. Custom questions match on question text or `column_id`, so a question like "Which treatment are you interested in?" fills the deal's treatment interest. Phones go through the same `normalise_phone()` as Facebook/Excel: numbers without a leading `+` are assumed to be `DEFAULT_COUNTRY_CODE`.
- Test leads (`is_test: true`, from **Send test data**): when accepted they always create a separate customer named `[TEST] …`, tagged `test_lead`, never merged into a real customer. Deleting that customer and sending test data again creates a fresh one.

Env vars (read from `.env` via the api service's `env_file`):

- `GOOGLE_ADS_WEBHOOK_KEY` (required) — long random string, e.g. `openssl rand -hex 32`
- `GOOGLE_ADS_ACCEPT_TEST_LEADS` (default `true`) — set `false` to acknowledge test leads with 200 but write nothing

Leads are owned by `FACEBOOK_DEFAULT_OWNER_USER_ID` (or the newest user if unset).

Setup in Google Ads: campaign → **Assets** → lead form → **Lead delivery options** → **Webhook integration**; Webhook URL `https://<public-api-host>/webhooks/google/ads-lead`, Key = `GOOGLE_ADS_WEBHOOK_KEY`; click **Send test data**.

## Messaging automations

Two built-in automations live under **Automations** in the sidebar (`/workflows`). Admins switch them on or off, pick channels, edit templates and set the follow-up delay there.

- **Appointment confirmation**: sent only to people booked into a time slot of an event in the Events tab (status `booked`/`confirmed`). Leads, people linked to an event on their deal without a slot, and the pipeline's "appointment booked" stage on its own never trigger it. Templates use `{{first_name}}`, `{{event_date}}`, `{{slot}}` (start to end, UK time) and `{{event_venue}}`; manual emails and WhatsApp quick messages resolve the same fields and refuse to send if the person has no usable booking. The date, time and location come from the booked slot. Slot times are shown as UK time (Europe/London, GMT/BST). If a confirmed booking moves to a new slot, an updated confirmation is sent (this can be switched off). Bookings with an unclear slot, such as no event location or a time that isn't on the timetable, are held under "Needs attention" instead of being sent.
- **Lead follow-up**: one message, a configurable delay after the lead is created (24 h by default), to leads with no event booking (their pipeline stage doesn't matter). It's stopped by actual contact: a sent message, a logged call or outbound message (internal notes don't count), a confirmation, staff opting them out (do not contact), or staff excluding them. Opening a WhatsApp chat from the CRM is not contact. While a staff message is queued but not yet sent, the follow-up waits and re-checks once it is sent (stop) or fails (carry on).

Each automation can **Send automatically** or **Require staff approval**. **Upcoming recipients** on the Automations page lists who is due a message, with the planned time and (for events) the booked date, slot and venue; staff can preview the exact formatted message and approve it. **Hold** pauses a message until a staff member releases it (it stays in the automation, however long the hold); **Exclude** removes the recipient from the automation.

**Existing records.** When an automation is switched on, records from before that moment (eligible leads, and upcoming event bookings that haven't had a confirmation) are listed as *Existing record*. They are never sent automatically: staff tick the ones to include, then preview and approve each message. Leads and bookings created after activation follow the automation's setting.

**Approval and send-time checks.** Approving re-renders the message and must match the preview staff looked at (otherwise: "changed since you previewed it"). The approved message records the event date, slot and venue it was approved with. The automation re-checks queued messages about once a minute, and the worker checks again immediately before sending (`worker/app/send_guard.py`); if the recipient is no longer eligible the message is cancelled, and if an approved message's date, slot or venue changed it is stopped as *Needs re-approval* until staff preview and approve it again. Automatically sent (unapproved) messages are instead replaced with one rendered from the booking as it is now.

Holds, releases, exclusions, inclusions, approvals and send outcomes are recorded in the contact's activity log.

Automated WhatsApp only uses a Twilio Content template that has a Content SID **and** is ticked "Approved by WhatsApp" on the template; there is no free-form fallback. Changing the template text or SID clears the approval. Manual replies from the Inbox are unaffected.

How it works: the API runs a background tick every `AUTOMATIONS_TICK_SECONDS` (default 60; disable with `AUTOMATIONS_SCHEDULER_ENABLED=false`). Each decision is written to `automation_sends`, whose unique dedupe key prevents duplicates, and is queued as an `outbound_messages` row for the existing worker to send via SMTP or Twilio. Failed sends are shown to staff and never retried automatically.

Setup:
1. Email and WhatsApp go to any patient or lead with a valid email address / phone number (international format, e.g. +44…) who hasn't opted out. Contact details left on a lead form count as permission. When someone replies STOP or asks not to be contacted, tick **Patient has opted out of all contact** on their contact page (**Messaging permissions**). The default follow-up templates tell people they can reply STOP.
2. Fill in **Clinic contact details** on the Automations page.
3. For WhatsApp, create and approve the templates in Twilio, then paste each Content SID into its template. The `{{field}}` placeholders in the CRM copy map, in order, to the approved template's `{{1}}`, `{{2}}`, and so on.
4. Switch the automation on. Only bookings and leads created after that moment are handled; nothing is back-filled.
