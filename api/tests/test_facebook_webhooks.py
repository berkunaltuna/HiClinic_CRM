from __future__ import annotations


def test_meta_webhook_verification_success(client):
    from app.core.config import settings

    settings.facebook_verify_token = "verify-me"
    r = client.get(
        "/webhooks/meta/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200, r.text
    assert r.text == "12345"


def test_meta_webhook_verification_failure(client):
    from app.core.config import settings

    settings.facebook_verify_token = "verify-me"
    r = client.get(
        "/webhooks/meta/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 403, r.text


def test_meta_lead_webhook_creates_customer_deal_and_dedupes(client, db, token, monkeypatch):
    # Create at least one user so the webhook can assign ownership.
    assert token

    import app.services.facebook_leads as fb
    from app.db.models import Customer, Deal, FacebookLeadEvent, Interaction

    async def fake_fetch(lead_id: str) -> dict:
        assert lead_id == "lead-123"
        return {
            "id": lead_id,
            "page_id": "page-1",
            "form_id": "form-1",
            "campaign_id": "campaign-1",
            "campaign_name": "TMJ Campaign",
            "adgroup_id": "adset-1",
            "adgroup_name": "TMJ Ad Set",
            "ad_id": "ad-1",
            "ad_name": "TMJ Creative A",
            "field_data": [
                {"name": "full_name", "values": ["Jane Doe"]},
                {"name": "email", "values": ["jane@example.com"]},
                {"name": "phone_number", "values": ["07700900123"]},
            ],
        }

    monkeypatch.setattr(fb, "fetch_facebook_lead", fake_fetch)

    payload = {
        "object": "page",
        "entry": [
            {
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": "lead-123",
                            "page_id": "page-1",
                            "form_id": "form-1",
                            "adgroup_id": "adset-1",
                            "ad_id": "ad-1",
                        },
                    }
                ]
            }
        ],
    }

    r = client.post("/webhooks/meta/facebook", json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}

    customer = db.query(Customer).filter(Customer.email == "jane@example.com").first()
    assert customer is not None
    assert customer.name == "Jane Doe"
    assert customer.phone == "+447700900123"
    assert customer.stage == "contacted"
    assert {"facebook", "facebook_lead", "new_lead"}.issubset(set(customer.tag_names))

    deal = db.query(Deal).filter(Deal.customer_id == customer.id).first()
    assert deal is not None
    assert deal.status == "open"

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == "lead-123").first()
    assert event is not None
    assert event.customer_id == customer.id
    assert event.deal_id == deal.id

    interaction = db.query(Interaction).filter(Interaction.provider_message_id == "lead-123").first()
    assert interaction is not None
    assert interaction.subject == "Facebook Lead Form submission"

    # Duplicate delivery should not create a second customer/deal/event.
    r = client.post("/webhooks/meta/facebook", json=payload)
    assert r.status_code == 200, r.text
    assert db.query(Customer).filter(Customer.email == "jane@example.com").count() == 1
    assert db.query(Deal).filter(Deal.customer_id == customer.id).count() == 1
    assert db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == "lead-123").count() == 1
