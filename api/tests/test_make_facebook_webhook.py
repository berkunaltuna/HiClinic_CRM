from __future__ import annotations


def test_make_facebook_lead_creates_customer_deal_and_dedupes(client, db, token):
    assert token

    from app.db.models import Customer, Deal, FacebookLeadEvent, Interaction

    payload = {
        "lead_id": "make-lead-123",
        "page_id": "page-1",
        "form_id": "form-1",
        "campaign_id": "campaign-1",
        "campaign_name": "TMJ Campaign",
        "adset_id": "adset-1",
        "adset_name": "TMJ Ad Set",
        "ad_id": "ad-1",
        "ad_name": "TMJ Creative A",
        "full_name": "Jane Doe",
        "email": "jane.make@example.com",
        "phone": "07700900123",
        "company": "Health Journey",
    }

    r = client.post("/webhooks/make/facebook-lead", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert r.json()["leadgen_id"] == "make-lead-123"
    assert r.json()["deduped"] is False

    customer = db.query(Customer).filter(Customer.email == "jane.make@example.com").first()
    assert customer is not None
    assert customer.name == "Jane Doe"
    assert customer.phone == "+447700900123"
    assert customer.company == "Health Journey"
    assert customer.stage == "contacted"
    assert {"facebook", "facebook_lead", "new_lead"}.issubset(set(customer.tag_names))

    deal = db.query(Deal).filter(Deal.customer_id == customer.id).first()
    assert deal is not None
    assert deal.status == "open"

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == "make-lead-123").first()
    assert event is not None
    assert event.customer_id == customer.id
    assert event.deal_id == deal.id

    interaction = db.query(Interaction).filter(Interaction.provider_message_id == "make-lead-123").first()
    assert interaction is not None
    assert interaction.subject == "Facebook Lead Form submission"

    r = client.post("/webhooks/make/facebook-lead", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is True
    assert db.query(Customer).filter(Customer.email == "jane.make@example.com").count() == 1
    assert db.query(Deal).filter(Deal.customer_id == customer.id).count() == 1
    assert db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == "make-lead-123").count() == 1


def test_make_webhook_secret_is_checked(client, db, token):
    assert token

    from app.core.config import settings

    previous = settings.make_webhook_secret
    settings.make_webhook_secret = "secret-123"
    try:
        payload = {"lead_id": "secret-lead"}
        r = client.post("/webhooks/make/facebook-lead", json=payload)
        assert r.status_code == 403, r.text

        r = client.post(
            "/webhooks/make/facebook-lead",
            json=payload,
            headers={"X-Make-Secret": "secret-123"},
        )
        assert r.status_code == 200, r.text
    finally:
        settings.make_webhook_secret = previous
