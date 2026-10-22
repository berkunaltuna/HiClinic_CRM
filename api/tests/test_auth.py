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
