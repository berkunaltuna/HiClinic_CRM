from __future__ import annotations

import os
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Phase 2: ensure we have an admin email available during tests.
# Must be set BEFORE importing the app/config.
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")
os.environ.setdefault("EMAIL_PROVIDER", "fake")

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.core.config import settings


@pytest.fixture(scope="session")
def engine():
    """
    Use the same DATABASE_URL as the app (default: Postgres in docker compose).
    For repeatability, we drop & recreate all tables once per test session.
    """
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    url = str(settings.database_url)
    if "test" not in url:
        raise RuntimeError(f"Refusing to run tests on non-test database: {url}")

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def db(engine):
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db) -> Generator[TestClient, None, None]:
    # Dependency override so API uses our test session.
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture()
def user_credentials():
    return {"email": _email(), "password": "ChangeMe123!"}


@pytest.fixture()
def token(client: TestClient, user_credentials) -> str:
    r = client.post("/auth/register", json=user_credentials)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_credentials():
    # Must match ADMIN_EMAILS above
    return {"email": "admin@example.com", "password": "ChangeMe123!"}


@pytest.fixture()
def admin_token(client: TestClient, admin_credentials) -> str:
    # Try registering first
    r = client.post("/auth/register", json=admin_credentials)
    if r.status_code == 201:
        return r.json()["access_token"]
    # If already registered, login instead
    if r.status_code == 400 and "already" in r.text.lower():
        r2 = client.post("/auth/login", json=admin_credentials)
        assert r2.status_code == 200, r2.text
        return r2.json()["access_token"]
    # Any other failure should fail the test setup
    assert False, f"Unexpected register response: {r.status_code} {r.text}"

@pytest.fixture()
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}
