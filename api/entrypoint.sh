#!/usr/bin/env sh
set -eu

# Ensure the application package (./app) is importable for alembic and uvicorn.
# (Some environments run entrypoints with a working directory that is not /app.)
export PYTHONPATH="/app"

# Apply DB migrations before starting the API.
# This keeps Phase 1 reproducible and avoids manual steps.
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[api] running migrations..."
  alembic upgrade head
else
  echo "[api] DATABASE_URL not set; skipping migrations"
fi

echo "[api] starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
