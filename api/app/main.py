from __future__ import annotations

import os
from fastapi import FastAPI

app = FastAPI(title="Minimal CRM API", version=os.getenv("APP_VERSION", "0.0.0"))


@app.get("/health")
def health() -> dict:
    """Phase 0 health endpoint.

    Note: We intentionally keep this lightweight and do not depend on the DB.
    DB readiness is handled by docker-compose healthcheck on Postgres.
    """
    return {
        "status": "ok",
        "service": "api",
        "version": os.getenv("APP_VERSION", "0.0.0"),
    }
