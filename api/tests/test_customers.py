from datetime import datetime, timezone


def test_customer_crud_roundtrip(client, auth_headers):
    # Create
    payload = {
        "name": "Acme Ltd",
        "email": "sales@acme.com",
        "phone": "+90 555 000 0000",
        "company": "Acme",
        "next_follow_up_at": None,
    }
    r = client.post("/customers", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    cust = r.json()
    assert "id" in cust
    customer_id = cust["id"]

    # List
    r = client.get("/customers", headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()]
    assert customer_id in ids

    # Get
    r = client.get(f"/customers/{customer_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == customer_id

    # Update
    r = client.patch(
        f"/customers/{customer_id}",
        json={"company": "Acme UK"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["company"] == "Acme UK"


def test_customer_ownership_enforced(client):
    # User A
    a = {"email": "a@example.com", "password": "ChangeMe123!"}
    r = client.post("/auth/register", json=a)
    assert r.status_code == 201, r.text
    token_a = r.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Create customer as A
    r = client.post(
        "/customers",
        json={"name": "Owned by A", "email": None, "phone": None, "company": None, "next_follow_up_at": None},
        headers=headers_a,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    # User B
    b = {"email": "b@example.com", "password": "ChangeMe123!"}
    r = client.post("/auth/register", json=b)
    assert r.status_code == 201, r.text
    token_b = r.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # B should not access A's customer
    r = client.get(f"/customers/{customer_id}", headers=headers_b)
    assert r.status_code in (403, 404), r.text
