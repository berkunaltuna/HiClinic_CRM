"""Test-only account creation. Public registration is closed, so tests insert staff
accounts directly (as an admin or the first-admin CLI would) and sign in normally."""

from __future__ import annotations

from app.auth.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal

DEFAULT_PASSWORD = "ChangeMe123!"


def ensure_account(email: str, password: str = DEFAULT_PASSWORD, role: str = "user") -> None:
    with SessionLocal() as s:
        if s.query(User.id).filter(User.email == email.lower()).first() is None:
            s.add(User(email=email.lower(), password_hash=hash_password(password), role=role))
            s.commit()


def staff_token(client, email: str, password: str = DEFAULT_PASSWORD, role: str = "user") -> str:
    ensure_account(email, password, role)
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
