from __future__ import annotations

from fastapi.testclient import TestClient


def test_templates_admin_only_write(client: TestClient, auth_headers: dict, admin_headers: dict):
    # Non-admin cannot create
    r = client.post(
        "/templates",
        json={"channel": "email", "name": "Welcome", "subject": "Hi", "body": "Hello {{customer_name}}"},
        headers=auth_headers,
    )
    assert r.status_code == 403, r.text

    # Admin can create
    r = client.post(
        "/templates",
        json={"channel": "email", "name": "Welcome", "subject": "Hi", "body": "Hello {{customer_name}}"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tpl = r.json()
    tpl_id = tpl["id"]

    # Any authenticated user can list/read
    r = client.get("/templates", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(t["id"] == tpl_id for t in r.json())

    r = client.get(f"/templates/{tpl_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Welcome"

    # Admin can update
    r = client.patch(
        f"/templates/{tpl_id}",
        json={"body": "Updated body"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "Updated body"

    # Admin can delete
    r = client.delete(f"/templates/{tpl_id}", headers=admin_headers)
    assert r.status_code == 204, r.text
