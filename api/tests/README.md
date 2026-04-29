# Automated tests (Phase 1)

These tests cover the Phase 1 routes:
- /auth/register, /auth/login
- /customers CRUD + ownership enforcement
- /deals create/list/update
- /interactions create/list
- /followups list
- /health

## Run locally (recommended: inside docker compose)

1) Start services:
   docker compose up -d --build

2) Exec into the API container and run pytest:
   docker compose exec api sh -lc "pip install -r requirements-dev.txt && pytest -q"

## Run from host (if you have Python deps installed)

From ./api:
   pip install -r requirements.txt -r requirements-dev.txt
   export DATABASE_URL="postgresql+psycopg://crm:crm@localhost:5432/crm"
   pytest -q
