from __future__ import annotations

from fastapi.testclient import TestClient


def test_template_preview_and_fake_email_send(client: TestClient, auth_headers: dict, admin_headers: dict):
    # Create email template (admin)
    r = client.post(
        "/templates",
        json={
            "channel": "email",
            "name": "InitialReply",
            "subject": "Hello {{customer_name}}",
            "body": "Hi {{customer_name}}, welcome to {{company}}.",
            "category": "transactional",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tpl_id = r.json()["id"]

    # Create customer
    r = client.post(
        "/customers",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "company": "HealthClinicTurkiye",
            "can_contact": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    # Preview template
    r = client.post(
        f"/templates/{tpl_id}/preview",
        json={"customer_id": customer_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["subject"] == "Hello Alice"
    assert "welcome to HealthClinicTurkiye" in r.json()["body"]

    # Send email (fake provider)
    r = client.post(
        f"/customers/{customer_id}/email/send",
        json={"template_id": tpl_id},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["provider_message_id"].startswith("fake-")
    assert out["interaction_id"]

    # Interaction should be present
    r = client.get(f"/customers/{customer_id}/interactions", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    first = items[0]
    assert first["channel"] == "email"
    assert first["direction"] == "outbound"
    assert first["provider_message_id"].startswith("fake-")
    assert first["subject"] == "Hello Alice"
    assert "welcome to HealthClinicTurkiye" in (first["content"] or "")


def test_send_email_blocked_when_cannot_contact(client: TestClient, auth_headers: dict, admin_headers: dict):
    # Template
    r = client.post(
        "/templates",
        json={
            "channel": "email",
            "name": "MarketingPing",
            "subject": "Promo {{customer_name}}",
            "body": "Hello {{customer_name}}",
            "category": "marketing",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tpl_id = r.json()["id"]

    # Customer who cannot be contacted
    r = client.post(
        "/customers",
        json={
            "name": "Bob",
            "email": "bob@example.com",
            "company": "Acme",
            "can_contact": False,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    r = client.post(
        f"/customers/{customer_id}/email/send",
        json={"template_id": tpl_id},
        headers=auth_headers,
    )
    assert r.status_code == 403, r.text
