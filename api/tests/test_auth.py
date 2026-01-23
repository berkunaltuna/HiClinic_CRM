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
