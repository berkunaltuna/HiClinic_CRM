import io
import uuid

import pytest
from sqlalchemy.orm import Session

from accounts import DEFAULT_PASSWORD, staff_token
from app.cli import FirstAdminError, create_first_admin, main as cli_main
from app.core.config import settings
from app.db.models import AuditLog, User, UserRole


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def test_public_registration_is_closed_for_everyone(client, db, monkeypatch):
    allowlisted = _uniq("allowlisted")
    # Even an address listed in ADMIN_EMAILS cannot create an account, let alone an admin.
    monkeypatch.setattr(settings, "admin_emails", [allowlisted, "admin@example.com"])
    for email in (_uniq("stranger"), allowlisted, "admin@example.com"):
        r = client.post("/auth/register", json={"email": email, "password": DEFAULT_PASSWORD})
        assert r.status_code == 403, r.text
        assert "access_token" not in r.text
    db.expire_all()
    assert db.query(User).filter(User.email == allowlisted).first() is None
    assert client.get("/auth/me", headers={"Authorization": "Bearer x"}).status_code == 401


def test_login_returns_token(client, user_credentials):
    staff_token(client, user_credentials["email"], user_credentials["password"])
    r = client.post("/auth/login", json=user_credentials)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    assert body.get("token_type") == "bearer"


def test_customers_requires_auth(client):
    r = client.get("/customers")
    assert r.status_code == 401


def test_me_returns_plain_role(client, admin_headers):
    r = client.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_admin_creates_staff_accounts(client, admin_headers):
    email = _uniq("doc")
    r = client.post("/users", json={"email": email, "password": DEFAULT_PASSWORD, "role": "doctor"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "doctor"
    r = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert r.status_code == 200
    staff = r.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {staff}"}).json()["role"] == "doctor"

    # Only admins can create accounts (and so only admins can create admins); roles are validated.
    assert client.post("/users", json={"email": _uniq("x"), "password": DEFAULT_PASSWORD, "role": "admin"}, headers={"Authorization": f"Bearer {staff}"}).status_code == 403
    assert client.post("/users", json={"email": _uniq("x"), "password": DEFAULT_PASSWORD}).status_code == 401
    assert client.post("/users", json={"email": _uniq("y"), "password": DEFAULT_PASSWORD, "role": "superuser"}, headers=admin_headers).status_code == 400
    assert client.post("/users", json={"email": email, "password": DEFAULT_PASSWORD}, headers=admin_headers).status_code == 400


def test_existing_users_can_still_reset_password_and_log_in(client, admin_headers):
    email = _uniq("reset")
    assert client.post("/users", json={"email": email, "password": DEFAULT_PASSWORD, "role": "coordinator"}, headers=admin_headers).status_code == 201
    r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 200 and r.json()["reset_url"]
    token = r.json()["reset_url"].split("token=", 1)[1]
    assert client.post("/auth/reset-password", json={"token": token, "password": "BrandNew456!"}).status_code == 200
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": "BrandNew456!"}).status_code == 200


@pytest.fixture()
def no_admin_db(engine):
    """A session in a transaction where no admin exists; everything is rolled back afterwards."""
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    session.query(User).filter(User.role == UserRole.admin).update({User.role: UserRole.user}, synchronize_session=False)
    session.flush()
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


def test_first_admin_setup_works_only_once(no_admin_db):
    email = _uniq("first_admin")
    user = create_first_admin(no_admin_db, email, "FirstAdmin123!")
    assert user.role == UserRole.admin
    assert no_admin_db.query(AuditLog).filter(AuditLog.action == "user.first_admin_created", AuditLog.entity_id == user.id).count() == 1

    with pytest.raises(FirstAdminError, match="already exists"):
        create_first_admin(no_admin_db, _uniq("second_admin"), "SecondAdmin123!")
    assert no_admin_db.query(User).filter(User.role == UserRole.admin).count() == 1


def test_first_admin_validates_input(no_admin_db):
    with pytest.raises(FirstAdminError, match="Password"):
        create_first_admin(no_admin_db, _uniq("short"), "short")
    with pytest.raises(FirstAdminError, match="Invalid email"):
        create_first_admin(no_admin_db, "not-an-email", "LongEnough123!")
    existing = _uniq("existing")
    staff_email_user = User(email=existing, password_hash="x", role=UserRole.user)
    no_admin_db.add(staff_email_user)
    no_admin_db.flush()
    with pytest.raises(FirstAdminError, match="already has an account"):
        create_first_admin(no_admin_db, existing, "LongEnough123!")
    assert no_admin_db.query(User).filter(User.role == UserRole.admin).count() == 0


def test_first_admin_cli(no_admin_db):
    out, err = io.StringIO(), io.StringIO()
    email = _uniq("cli_admin")
    code = cli_main(
        ["create-first-admin", "--email", email, "--password-stdin"],
        session_factory=lambda: no_admin_db,
        stdin=io.StringIO("CliAdmin12345!\n"),
        out=out,
        err=err,
    )
    assert code == 0, err.getvalue()
    assert email in out.getvalue()


def test_first_admin_cli_refuses_when_an_admin_exists(client, admin_headers):
    # The real test database already has an admin, so the CLI must refuse.
    out, err = io.StringIO(), io.StringIO()
    code = cli_main(["create-first-admin", "--email", _uniq("late"), "--password-stdin"], stdin=io.StringIO("LateAdmin123!\n"), out=out, err=err)
    assert code == 1 and "already exists" in err.getvalue()


def _jwt(claims: dict) -> str:
    import jwt
    from app.core.config import settings

    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_password_reset_token_is_not_an_access_token(client, user_credentials):
    from app.api.auth import _password_reset_token
    from app.db.models import User

    staff_token(client, user_credentials["email"], user_credentials["password"])
    r = client.post("/auth/login", json=user_credentials)
    assert r.status_code == 200, r.text
    login_token = r.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {login_token}"}).status_code == 200

    user_id = client.get("/auth/me", headers={"Authorization": f"Bearer {login_token}"}).json()["id"]
    reset_token = _password_reset_token(User(id=__import__("uuid").UUID(user_id)))
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {reset_token}"})
    assert r.status_code == 401


def test_access_token_type_rules(client, user_credentials):
    import time

    login_token = staff_token(client, user_credentials["email"], user_credentials["password"])
    user_id = client.get("/auth/me", headers={"Authorization": f"Bearer {login_token}"}).json()["id"]
    now = int(time.time())
    base = {"sub": user_id, "iat": now, "exp": now + 600}

    def me(claims):
        return client.get("/auth/me", headers={"Authorization": f"Bearer {_jwt(claims)}"}).status_code

    assert me({**base, "typ": "access"}) == 200
    # Pre-`typ` access tokens (exactly sub/iat/exp) keep working until they expire.
    assert me(base) == 200
    assert me({**base, "typ": "refresh"}) == 401
    assert me({**base, "typ": "access", "purpose": "password_reset"}) == 401
    assert me({**base, "aud": "patient-portal"}) == 401
