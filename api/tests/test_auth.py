def test_register_returns_token(client, user_credentials):
    r = client.post("/auth/register", json=user_credentials)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body
    assert body.get("token_type") == "bearer"


def test_login_returns_token(client, user_credentials):
    # Register first
    r = client.post("/auth/register", json=user_credentials)
    assert r.status_code == 201, r.text

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


def test_public_registration_is_closed_by_default(client, monkeypatch, admin_headers):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_public_registration", False)
    r = client.post("/auth/register", json={"email": "stranger@example.com", "password": "ChangeMe123!"})
    assert r.status_code == 403

    # An admin creates staff accounts instead; they sign in normally.
    email = f"doc_{__import__('uuid').uuid4().hex[:8]}@example.com"
    r = client.post("/users", json={"email": email, "password": "ChangeMe123!", "role": "doctor"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "doctor"
    r = client.post("/auth/login", json={"email": email, "password": "ChangeMe123!"})
    assert r.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "doctor"

    # Only admins can create accounts; roles are validated.
    staff = client.post("/auth/login", json={"email": email, "password": "ChangeMe123!"}).json()["access_token"]
    assert client.post("/users", json={"email": "x" + email, "password": "ChangeMe123!"}, headers={"Authorization": f"Bearer {staff}"}).status_code == 403
    assert client.post("/users", json={"email": "y" + email, "password": "ChangeMe123!", "role": "superuser"}, headers=admin_headers).status_code == 400
    assert client.post("/users", json={"email": email, "password": "ChangeMe123!"}, headers=admin_headers).status_code == 400


def test_admin_email_can_still_bootstrap_when_registration_closed(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_public_registration", False)
    email = f"boot_{__import__('uuid').uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(settings, "admin_emails", [email])
    r = client.post("/auth/register", json={"email": email, "password": "ChangeMe123!"})
    assert r.status_code == 201, r.text
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "admin"


def _jwt(claims: dict) -> str:
    import jwt
    from app.core.config import settings

    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_password_reset_token_is_not_an_access_token(client, user_credentials):
    from app.api.auth import _password_reset_token
    from app.db.models import User

    r = client.post("/auth/register", json=user_credentials)
    assert r.status_code == 201, r.text
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

    r = client.post("/auth/register", json=user_credentials)
    assert r.status_code == 201, r.text
    login_token = r.json()["access_token"]
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
