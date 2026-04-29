from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="Minimal CRM API", version=os.getenv("APP_VERSION", "0.0.0"))

# Allow the CRM frontend (running on a different origin, e.g. :3000) to call the API.
# Without this, browser requests will fail even if the endpoints work in Swagger/curl.
origins = settings.cors_origins or ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Some environments (reverse proxies / certain dev setups) can still surface
# preflight OPTIONS as 405 before CORS middleware is applied. This catch-all
# ensures browsers can complete preflight for any path.
@app.options("/{rest_of_path:path}")
def preflight_handler(request: Request, rest_of_path: str) -> Response:  # noqa: ARG001
    origin = request.headers.get("origin")
    req_headers = request.headers.get("access-control-request-headers", "*")
    headers = {
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": req_headers,
    }
    # Reflect allowed origin (do NOT use '*' when credentials are allowed)
    if origin and (
        origin in settings.cors_origins
        or origin.startswith("http://localhost")
        or origin.startswith("http://127.0.0.1")
    ):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return Response(status_code=200, headers=headers)

app.include_router(api_router)


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
