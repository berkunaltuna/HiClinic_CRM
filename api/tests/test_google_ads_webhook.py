from __future__ import annotations

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Customer, Deal, DealStatus, FacebookLeadEvent, Interaction, User
from app.services import facebook_leads, google_ads_leads
from app.services.google_ads_leads import handle_google_ads_lead

URL = "/webhooks/google/ads-lead"
KEY = "g-key-123"

# Verbatim from https://developers.google.com/google-ads/webhook/docs/testing
# (only google_key changed to our configured key).
GOOGLE_DOC_TEST_PAYLOAD = {
    "lead_id": "Cj0KCQjwit_8BRCoARIsAIx3Rj7g-AeL6z35IWb6VYiZUygtTfwD3hDlgSGmY-XTTlK3lfV1wcuIwIAaAmMxEALw_wcB",
    "campaign_id": 123456,
    "adgroup_id": 0,
    "creative_id": 0,
    "gcl_id": "Cj0KCQjwit_8BRCoARIsAIx3Rj7g-AeL6z35IWb6VYiZUygtTfwD3hDlgSGmY-XTTlK3lfV1wcuIwIAaAmMxEALw_wcB",
    "user_column_data": [
        {"column_name": "Full Name", "string_value": "FirstName LastName", "column_id": "FULL_NAME"},
        {"column_name": "User Phone", "string_value": "1-650-555-0123", "column_id": "PHONE_NUMBER"},
        {"column_name": "User Email", "string_value": "test@example.com", "column_id": "EMAIL"},
    ],
    "api_version": "1.0",
    "form_id": 123456789,
    "google_key": KEY,
    "is_test": True,
}


@pytest.fixture(autouse=True)
def google_settings():
    saved = (
        settings.google_ads_webhook_key,
        settings.google_ads_accept_test_leads,
        settings.share_customers_across_users,
        settings.facebook_default_owner_user_id,
    )
    settings.google_ads_webhook_key = KEY
    settings.google_ads_accept_test_leads = True
    settings.share_customers_across_users = True  # production setting
    settings.facebook_default_owner_user_id = None  # default owner = newest user
    try:
        yield
    finally:
        (
            settings.google_ads_webhook_key,
            settings.google_ads_accept_test_leads,
            settings.share_customers_across_users,
            settings.facebook_default_owner_user_id,
        ) = saved


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _prod_payload(**overrides):
    u = _uid()
    payload = {
        "lead_id": f"lead-{u}",
        "api_version": "1.0",
        "form_id": 40000000000,
        "campaign_id": 12345678901,
        "adgroup_id": 20000000000,
        "creative_id": 30000000000,
        "asset_group_id": 50000000000,
        "gcl_id": f"gclid-{u}",
        "google_key": KEY,
        "is_test": False,
        "lead_submit_time": "2026-10-01T09:15:00+00:00",
        "lead_stage": "NEW",
        "lead_source": "LEAD_FORM",
        "user_column_data": [
            {"column_name": "First Name", "string_value": "Ada", "column_id": "FIRST_NAME"},
            {"column_name": "Last Name", "string_value": "Lovelace", "column_id": "LAST_NAME"},
            {"column_name": "User Email", "string_value": f"Ada.{u}@Example.com", "column_id": "EMAIL"},
            {"column_name": "User Phone", "string_value": f"+44 7700 9{int(u, 16) % 100000:05d}", "column_id": "PHONE_NUMBER"},
            # column_name is optional per Google's docs; match on column_id alone.
            {"string_value": "Hair Transplant", "column_id": "which_treatment_are_you_interested_in"},
        ],
    }
    payload.update(overrides)
    return payload


def _phone(payload):
    return next(c["string_value"] for c in payload["user_column_data"] if c["column_id"] == "PHONE_NUMBER")


def _email(payload):
    return next(c["string_value"] for c in payload["user_column_data"] if c["column_id"] == "EMAIL").lower()


def _counts(db):
    db.expire_all()
    return (
        db.query(Customer).count(),
        db.query(Deal).count(),
        db.query(Interaction).count(),
        db.query(FacebookLeadEvent).count(),
    )


def test_production_lead_maps_fields_and_attribution(client, db, token):
    payload = _prod_payload()
    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is False

    customer = db.query(Customer).filter(sa.func.lower(Customer.email) == _email(payload)).one()
    assert customer.name == "Ada Lovelace"
    assert customer.phone == "+" + "".join(ch for ch in _phone(payload) if ch.isdigit())
    assert customer.stage == "new"
    assert customer.lead_source == "google"
    assert (customer.form_id, customer.campaign_id, customer.adset_id, customer.ad_id) == (
        "40000000000", "12345678901", "20000000000", "30000000000",
    )
    assert customer.created_at.isoformat().startswith("2026-10-01T09:15")
    assert {"google", "google_ads_lead", "new_lead", "Hair Transplant"} <= set(customer.tag_names)
    assert not {"facebook", "facebook_lead", "test_lead"} & set(customer.tag_names)

    deal = db.query(Deal).filter(Deal.customer_id == customer.id).one()
    assert deal.treatment_interest == "Hair Transplant"

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == f"google:{payload['lead_id']}").one()
    assert (event.source, event.gclid, event.is_test) == ("google", payload["gcl_id"], False)
    assert (event.form_id, event.campaign_id, event.adset_id, event.ad_id) == (
        "40000000000", "12345678901", "20000000000", "30000000000",
    )
    assert "google_key" not in event.raw_payload
    assert event.raw_payload["asset_group_id"] == 50000000000

    interaction = db.query(Interaction).filter(Interaction.provider_message_id == event.leadgen_id).one()
    assert interaction.subject == "Google Ads Lead Form submission"
    for fragment in ('"source": "google"', payload["lead_id"], payload["gcl_id"], "50000000000", '"lead_stage": "NEW"'):
        assert fragment in interaction.content


def test_minimal_payload_with_missing_optional_fields(client, db, token):
    payload = {
        "lead_id": f"min-{_uid()}",
        "google_key": KEY,
        "user_column_data": [{"column_id": "EMAIL", "string_value": f"min.{_uid()}@example.com"}],
    }
    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    customer = db.query(Customer).filter(Customer.email == payload["user_column_data"][0]["string_value"]).one()
    assert customer.lead_source == "google"
    assert customer.campaign_id is None and customer.adset_id is None
    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == f"google:{payload['lead_id']}").one()
    assert event.gclid is None and event.is_test is False


def test_replay_creates_one_submission(client, db, token):
    payload = _prod_payload()
    assert client.post(URL, json=payload).json()["deduped"] is False
    before = _counts(db)
    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is True
    assert _counts(db) == before


def test_missing_or_wrong_key_creates_nothing(client, db, token):
    before = _counts(db)
    no_key = _prod_payload()
    del no_key["google_key"]
    assert client.post(URL, json=no_key).status_code == 403
    assert client.post(URL, json=_prod_payload(google_key="wrong")).status_code == 403
    settings.google_ads_webhook_key = None
    assert client.post(URL, json=_prod_payload()).status_code == 503  # retryable until configured
    assert _counts(db) == before


def test_key_field_spelling_from_google_samples_is_accepted(client, db, token):
    payload = _prod_payload()
    payload["Google_key"] = payload.pop("google_key")
    assert client.post(URL, json=payload).status_code == 200


def test_existing_customer_is_protected(client, db, token):
    other_user = User(email=f"other-{_uid()}@example.com", password_hash="x")
    db.add(other_user)
    db.flush()
    payload = _prod_payload()
    # Created by a different user, phone stored exactly as typed (not normalised).
    existing = Customer(
        owner_user_id=other_user.id,
        name="Original Name",
        phone="0" + "".join(ch for ch in _phone(payload) if ch.isdigit())[2:],
        stage="booked",
        lead_source="facebook",
        campaign_id="fb-campaign",
    )
    db.add(existing)
    db.flush()
    db.add(Deal(customer_id=existing.id, owner_user_id=other_user.id, amount=0,
                status=DealStatus.open, treatment_interest="Body Contouring"))
    db.commit()

    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["customer_id"] == str(existing.id)

    db.expire_all()
    customer = db.get(Customer, existing.id)
    assert customer.stage == "booked"
    assert customer.name == "Original Name"
    assert customer.lead_source == "facebook"
    assert customer.campaign_id == "fb-campaign"
    assert customer.adset_id is None and customer.form_id is None  # no mixing in Google ids
    assert "new_lead" not in customer.tag_names
    assert "google" in customer.tag_names  # submission source is still visible
    deals = db.query(Deal).filter(Deal.customer_id == existing.id).all()
    assert [d.treatment_interest for d in deals] == ["Body Contouring"]
    assert db.query(Customer).filter(sa.func.lower(Customer.email) == _email(payload)).count() <= 1

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == f"google:{payload['lead_id']}").one()
    assert event.source == "google" and event.campaign_id == "12345678901"
    interaction = db.query(Interaction).filter(Interaction.provider_message_id == event.leadgen_id).one()
    assert interaction.subject == "Google Ads Lead Form submission"
    assert "Hair Transplant" in interaction.content


def test_googles_documented_test_payload(client, db, token):
    # A real customer that shares the test payload's email must stay untouched.
    real = Customer(owner_user_id=db.query(User).first().id, name="Real Person", email="test@example.com", stage="booked")
    db.add(real)
    db.commit()

    r = client.post(URL, json=copy.deepcopy(GOOGLE_DOC_TEST_PAYLOAD))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_test"] is True and body["ingested"] is True
    assert body["customer_id"] != str(real.id)

    customer = db.get(Customer, uuid.UUID(body["customer_id"]))
    assert customer.name == "[TEST] FirstName LastName"
    assert customer.email == "test@example.com"
    # Same normalise_phone() as Facebook/Excel ingestion: no leading "+" means
    # DEFAULT_COUNTRY_CODE (+44) is assumed.
    assert customer.phone == "+4416505550123"
    assert {"google", "test_lead"} <= set(customer.tag_names)
    assert customer.campaign_id == "123456" and customer.adset_id is None and customer.ad_id is None
    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.customer_id == customer.id).one()
    assert event.is_test is True
    interaction = db.query(Interaction).filter(Interaction.customer_id == customer.id).one()
    assert interaction.subject == "[TEST] Google Ads Lead Form submission"

    db.expire_all()
    assert db.get(Customer, real.id).tag_names == []

    # Deleting the test customer and pressing "Send test data" again works.
    r = client.delete(f"/customers/{customer.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204, r.text
    r = client.post(URL, json=copy.deepcopy(GOOGLE_DOC_TEST_PAYLOAD))
    assert r.status_code == 200, r.text
    assert r.json()["customer_id"] not in (None, body["customer_id"])


def test_disabled_test_leads_are_acknowledged_without_changes(client, db, token):
    settings.google_ads_accept_test_leads = False
    before = _counts(db)
    payload = copy.deepcopy(GOOGLE_DOC_TEST_PAYLOAD)
    payload["lead_id"] = f"disabled-{_uid()}"
    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "lead_id": payload["lead_id"], "is_test": True, "ingested": False}
    assert _counts(db) == before


def test_failed_processing_leaves_nothing_and_retry_succeeds(db, token, monkeypatch):
    payload = _prod_payload()
    before = _counts(db)
    real_add_tag = facebook_leads.add_tag_to_customer
    calls = {"n": 0}

    def flaky_add_tag(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure mid-ingest")
        return real_add_tag(*args, **kwargs)

    monkeypatch.setattr(facebook_leads, "add_tag_to_customer", flaky_add_tag)
    with pytest.raises(RuntimeError):
        handle_google_ads_lead(payload, db)
    assert _counts(db) == before

    monkeypatch.setattr(facebook_leads, "add_tag_to_customer", real_add_tag)
    result = handle_google_ads_lead(payload, db)
    assert result["deduped"] is False and result["customer_id"]
    assert db.query(Customer).filter(sa.func.lower(Customer.email) == _email(payload)).count() == 1


def test_concurrent_duplicate_deliveries(engine, db, token, monkeypatch):
    # Fresh owner so both requests also race to create the same tags.
    db.add(User(email=f"race-{_uid()}@example.com", password_hash="x"))
    db.commit()
    payload = _prod_payload()
    before = _counts(db)

    # Hold both requests after their "already ingested?" check so they really overlap.
    barrier = threading.Barrier(2, timeout=10)
    real_owner = google_ads_leads._get_default_owner

    def owner_after_barrier(session):
        barrier.wait()
        return real_owner(session)

    monkeypatch.setattr(google_ads_leads, "_get_default_owner", owner_after_barrier)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def deliver():
        session = Session()
        try:
            return handle_google_ads_lead(copy.deepcopy(payload), session)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(deliver), pool.submit(deliver)]]

    assert sorted(r["deduped"] for r in results) == [False, True]
    assert results[0]["customer_id"] == results[1]["customer_id"]
    after = _counts(db)
    assert tuple(a - b for a, b in zip(after, before)) == (1, 1, 1, 1)
