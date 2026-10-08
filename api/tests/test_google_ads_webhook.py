from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture()
def google_key():
    previous = settings.google_ads_webhook_key
    settings.google_ads_webhook_key = "g-key-123"
    try:
        yield "g-key-123"
    finally:
        settings.google_ads_webhook_key = previous


def _payload(google_key: str, **overrides):
    payload = {
        "lead_id": "TeSter-123-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "api_version": "1.0",
        "form_id": 40000000000,
        "campaign_id": 12345678901,
        "adgroup_id": 20000000000,
        "creative_id": 30000000000,
        "gcl_id": "gclid-abc",
        "google_key": google_key,
        "is_test": False,
        "lead_submit_time": "2026-10-01 09:15:00+00:00",
        "user_column_data": [
            {"column_name": "First Name", "string_value": "Ada", "column_id": "FIRST_NAME"},
            {"column_name": "Last Name", "string_value": "Lovelace", "column_id": "LAST_NAME"},
            {"column_name": "User Email", "string_value": "ada.google@example.com", "column_id": "EMAIL"},
            {"column_name": "User Phone", "string_value": "07700900555", "column_id": "PHONE_NUMBER"},
            {
                "column_name": "Which treatment are you interested in?",
                "string_value": "Hair Transplant",
                "column_id": "which_treatment",
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_google_ads_lead_creates_customer_deal_and_dedupes(client, db, token, google_key):
    assert token

    from app.db.models import Customer, Deal, FacebookLeadEvent, Interaction

    r = client.post("/webhooks/google/ads-lead", json=_payload(google_key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["deduped"] is False
    assert body["ingested"] is True

    customer = db.query(Customer).filter(Customer.email == "ada.google@example.com").first()
    assert customer is not None
    assert customer.name == "Ada Lovelace"
    assert customer.phone == "+447700900555"
    assert customer.lead_source == "google"
    assert customer.campaign_id == "12345678901"
    assert customer.adset_id == "20000000000"
    assert customer.ad_id == "30000000000"
    assert customer.created_at.year == 2026 and customer.created_at.month == 10
    tags = set(customer.tag_names)
    assert {"google", "google_ads_lead", "new_lead", "Hair Transplant"}.issubset(tags)
    assert "facebook" not in tags

    deal = db.query(Deal).filter(Deal.customer_id == customer.id).one()
    assert deal.treatment_interest == "Hair Transplant"

    event = db.query(FacebookLeadEvent).filter(
        FacebookLeadEvent.leadgen_id == "google:TeSter-123-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ).one()
    assert event.customer_id == customer.id
    assert "google_key" not in event.raw_payload

    interaction = db.query(Interaction).filter(Interaction.provider_message_id == event.leadgen_id).one()
    assert interaction.subject == "Google Ads Lead Form submission"

    # Google retries deliveries; a replay must not duplicate anything.
    r = client.post("/webhooks/google/ads-lead", json=_payload(google_key))
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is True
    assert db.query(Customer).filter(Customer.email == "ada.google@example.com").count() == 1
    assert db.query(Deal).filter(Deal.customer_id == customer.id).count() == 1


def test_google_ads_lead_rejects_bad_or_missing_key(client, db, google_key):
    r = client.post("/webhooks/google/ads-lead", json=_payload("wrong"))
    assert r.status_code == 403, r.text

    settings.google_ads_webhook_key = None
    r = client.post("/webhooks/google/ads-lead", json=_payload("anything"))
    assert r.status_code == 503, r.text


def test_google_ads_test_lead_tagged_or_skipped(client, db, token, google_key):
    assert token

    from app.db.models import Customer

    r = client.post(
        "/webhooks/google/ads-lead",
        json=_payload(
            google_key,
            lead_id="test-lead-1",
            is_test=True,
            user_column_data=[
                {"column_name": "Full Name", "string_value": "Test User", "column_id": "FULL_NAME"},
                {"column_name": "User Email", "string_value": "test.google@example.com", "column_id": "EMAIL"},
            ],
        ),
    )
    assert r.status_code == 200, r.text
    customer = db.query(Customer).filter(Customer.email == "test.google@example.com").one()
    assert "test_lead" in set(customer.tag_names)

    previous = settings.google_ads_accept_test_leads
    settings.google_ads_accept_test_leads = False
    try:
        r = client.post(
            "/webhooks/google/ads-lead",
            json=_payload(google_key, lead_id="test-lead-2", is_test=True),
        )
        assert r.status_code == 200, r.text
        assert r.json()["ingested"] is False
    finally:
        settings.google_ads_accept_test_leads = previous
