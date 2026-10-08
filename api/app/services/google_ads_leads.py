"""Google Ads lead form webhook ingestion.

Payload reference: https://developers.google.com/google-ads/webhook/docs/implementation
Google retries 5xx responses but treats 4xx as permanent, so anything that is
our own misconfiguration (no key set, no owner user) must surface as 5xx.
"""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Customer, FacebookLeadEvent, User
from app.services.facebook_leads import _coalesce, _get_default_owner, _ingest_graph_style_lead
from app.services.matching import find_customer_candidates, normalise_email

# Standard lead form questions have fixed column_ids; map them onto the field
# names the shared ingestion already understands.
STANDARD_COLUMN_FIELD_MAP = {
    "FULL_NAME": "full_name",
    "EMAIL": "email",
    "WORK_EMAIL": "email",
    "PHONE_NUMBER": "phone_number",
    "WORK_PHONE": "phone_number",
    "COMPANY_NAME": "company_name",
}

# Dedup keys share facebook_lead_events.leadgen_id with Meta leads; prefix so
# ids from the two platforms can never collide.
DEDUP_PREFIX = "google:"
TEST_PREFIX = "[TEST] "


def _google_key_from_payload(payload: dict[str, Any]) -> str:
    # Google's own sample payloads spell it both google_key and Google_key.
    for key, value in payload.items():
        if str(key).lower() == "google_key":
            return str(value or "").strip()
    return ""


def validate_google_key(payload: dict[str, Any]) -> None:
    expected = (settings.google_ads_webhook_key or "").strip()
    if not expected:
        # 5xx so Google keeps retrying until the key is configured.
        raise HTTPException(status_code=503, detail="GOOGLE_ADS_WEBHOOK_KEY is not configured")
    actual = _google_key_from_payload(payload)
    if not hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Invalid google_key")


def _id(value: Any) -> str | None:
    # Google sends 0 for ids that don't apply (e.g. adgroup_id outside video/discovery).
    text = _coalesce(value)
    return None if text in (None, "0") else text


def _field_data_from_user_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field_data: list[dict[str, Any]] = []
    first_name: str | None = None
    last_name: str | None = None
    has_full_name = False

    for column in columns or []:
        if not isinstance(column, dict):
            continue
        value = _coalesce(column.get("string_value"))
        if not value:
            continue
        column_id = str(column.get("column_id") or "").strip()
        standard_id = column_id.upper()
        if standard_id == "FIRST_NAME":
            first_name = value
            continue
        if standard_id == "LAST_NAME":
            last_name = value
            continue
        standard_name = STANDARD_COLUMN_FIELD_MAP.get(standard_id)
        if standard_name:
            has_full_name = has_full_name or standard_name == "full_name"
            field_data.append({"name": standard_name, "values": [value]})
            continue
        # Custom/qualifying question. column_name (the question text) is
        # optional per Google's docs, so offer both it and column_id to the
        # fuzzy treatment/day/seminar matching.
        for name in dict.fromkeys(n for n in (_coalesce(column.get("column_name")), column_id or None) if n):
            field_data.append({"name": name, "values": [value]})

    if not has_full_name and (first_name or last_name):
        full_name = " ".join(part for part in (first_name, last_name) if part)
        field_data.insert(0, {"name": "full_name", "values": [full_name]})
    return field_data


def _mark_test_name(field_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    marked = [item for item in field_data if item["name"] != "full_name"]
    name = next((item["values"][0] for item in field_data if item["name"] == "full_name"), "Google test lead")
    return [{"name": "full_name", "values": [f"{TEST_PREFIX}{name}"]}, *marked]


def _graph_lead_from_google_payload(payload: dict[str, Any], dedup_key: str, is_test: bool) -> dict[str, Any]:
    field_data = _field_data_from_user_columns(payload.get("user_column_data") or [])
    if is_test:
        field_data = _mark_test_name(field_data)
    return {
        "id": dedup_key,
        "form_id": _id(payload.get("form_id")),
        "campaign_id": _id(payload.get("campaign_id")),
        "adgroup_id": _id(payload.get("adgroup_id")),
        "ad_id": _id(payload.get("creative_id")),
        "platform": "google",
        "created_time": _coalesce(payload.get("lead_submit_time")),
        "field_data": field_data,
    }


def _find_google_customer(db: Session, owner: User, email: str | None, phone: str | None) -> Customer | None:
    """Match like the Excel importer does: respects SHARE_CUSTOMERS_ACROSS_USERS
    and matches un-normalised stored phones. Phone first, then email."""
    candidates = find_customer_candidates(db, owner, phone=phone, email=normalise_email(email))
    for matches in (candidates.phone_matches, candidates.email_matches):
        if matches:
            return min(matches, key=lambda c: c.created_at)
    return None


def _never_match(db: Session, owner: User, email: str | None, phone: str | None) -> None:
    return None


def _event(db: Session, dedup_key: str) -> FacebookLeadEvent | None:
    return db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == dedup_key).first()


def _ingest(db: Session, payload: dict[str, Any], lead_id: str, dedup_key: str, is_test: bool) -> None:
    try:
        owner = _get_default_owner(db)
    except HTTPException as exc:
        # No usable owner is our misconfiguration; make Google retry rather than drop the lead.
        raise HTTPException(status_code=503, detail=exc.detail) from exc

    attribution = {
        "source": "google",
        "google_lead_id": lead_id,
        "form_id": _id(payload.get("form_id")),
        "campaign_id": _id(payload.get("campaign_id")),
        "adgroup_id": _id(payload.get("adgroup_id")),
        "creative_id": _id(payload.get("creative_id")),
        "asset_group_id": _id(payload.get("asset_group_id")),
        "gcl_id": _coalesce(payload.get("gcl_id")),
        "lead_stage": _coalesce(payload.get("lead_stage")),
        "google_lead_source": _coalesce(payload.get("lead_source")),
        "is_test": is_test,
    }
    source_tags: tuple[str, ...] = ("google", "google_ads_lead")
    subject = "Google Ads Lead Form submission"
    if is_test:
        source_tags += ("test_lead",)
        subject = TEST_PREFIX + subject

    _ingest_graph_style_lead(
        db,
        lead=_graph_lead_from_google_payload(payload, dedup_key, is_test),
        lead_id=dedup_key,
        owner=owner,
        # Never persist the shared secret alongside the lead.
        raw_payload={k: v for k, v in payload.items() if str(k).lower() != "google_key"},
        interaction_subject=subject,
        source_tags=source_tags,
        fallback_name_prefix="Google Lead",
        # Test leads must never touch a real customer record.
        find_customer=_never_match if is_test else _find_google_customer,
        keep_existing_attribution=True,
        summary_extra=attribution,
        event_extra={"source": "google", "gclid": attribution["gcl_id"], "is_test": is_test},
    )


def handle_google_ads_lead(payload: dict[str, Any], db: Session) -> dict[str, Any]:
    validate_google_key(payload)

    lead_id = _coalesce(payload.get("lead_id"))
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")

    is_test = payload.get("is_test") is True or str(payload.get("is_test")).lower() == "true"
    if is_test and not settings.google_ads_accept_test_leads:
        return {"status": "ok", "lead_id": lead_id, "is_test": True, "ingested": False}

    dedup_key = f"{DEDUP_PREFIX}{lead_id}"
    existing_before = _event(db, dedup_key)
    if existing_before is not None and is_test and existing_before.customer_id is None:
        # The test customer from an earlier "Send test data" was deleted; let a
        # re-test create a fresh one instead of silently deduping.
        db.delete(existing_before)
        db.flush()
        existing_before = None

    deduped = existing_before is not None
    if not deduped:
        try:
            _ingest(db, payload, lead_id, dedup_key, is_test)
        except IntegrityError:
            # A concurrent delivery of the same lead_id committed first; its
            # unique leadgen_id wins and this whole transaction is discarded.
            db.rollback()
            if _event(db, dedup_key) is None:
                raise
            deduped = True
        except Exception:
            # Leave nothing half-written so Google's retry starts clean.
            db.rollback()
            raise

    event = _event(db, dedup_key)
    return {
        "status": "ok",
        "lead_id": lead_id,
        "is_test": is_test,
        "ingested": True,
        "customer_id": str(event.customer_id) if event and event.customer_id else None,
        "deal_id": str(event.deal_id) if event and event.deal_id else None,
        "deduped": deduped,
    }
