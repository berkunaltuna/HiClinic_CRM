from __future__ import annotations

import os
import tempfile
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
# Tests drive the automation tick explicitly instead of a background thread.
os.environ.setdefault("AUTOMATIONS_SCHEDULER_ENABLED", "false")
# Patient photos go to a throwaway private directory, never a real store.
os.environ.setdefault("PHOTO_STORAGE_DIR", tempfile.mkdtemp(prefix="crm-test-photos-"))

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.core.config import settings
from accounts import staff_token


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
    return staff_token(client, user_credentials["email"], user_credentials["password"])


@pytest.fixture()
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_credentials():
    # Must match ADMIN_EMAILS above
    return {"email": "admin@example.com", "password": "ChangeMe123!"}


@pytest.fixture()
def admin_token(client: TestClient, admin_credentials) -> str:
    return staff_token(client, admin_credentials["email"], admin_credentials["password"], role="admin")

@pytest.fixture()
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}
