from __future__ import annotations

import hmac
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import FacebookLeadEvent
from app.services.facebook_leads import _coalesce, _get_default_owner, _ingest_graph_style_lead

# Google Ads lead form webhook payloads carry answers in user_column_data, keyed
# by column_id. Standard questions use fixed ids; map them onto the field names
# the shared ingestion already understands. Custom questions keep their
# question text (column_name) so the fuzzy treatment/day/seminar matching works.
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


def validate_google_key(payload: dict[str, Any]) -> None:
    expected = (settings.google_ads_webhook_key or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="GOOGLE_ADS_WEBHOOK_KEY is not configured")
    actual = str(payload.get("google_key") or "").strip()
    if not hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Invalid google_key")


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
        column_id = str(column.get("column_id") or "").strip().upper()
        if column_id == "FIRST_NAME":
            first_name = value
            continue
        if column_id == "LAST_NAME":
            last_name = value
            continue
        name = STANDARD_COLUMN_FIELD_MAP.get(column_id) or _coalesce(column.get("column_name"), column.get("column_id"))
        if not name:
            continue
        if name == "full_name":
            has_full_name = True
        field_data.append({"name": name, "values": [value]})

    if not has_full_name and (first_name or last_name):
        full_name = " ".join(part for part in (first_name, last_name) if part)
        field_data.insert(0, {"name": "full_name", "values": [full_name]})
    return field_data


def _graph_lead_from_google_payload(payload: dict[str, Any], dedup_key: str) -> dict[str, Any]:
    return {
        "id": dedup_key,
        "form_id": _coalesce(payload.get("form_id")),
        "form_name": _coalesce(payload.get("form_name")),
        "campaign_id": _coalesce(payload.get("campaign_id")),
        "campaign_name": _coalesce(payload.get("campaign_name")),
        "adgroup_id": _coalesce(payload.get("adgroup_id")),
        "adgroup_name": _coalesce(payload.get("adgroup_name")),
        "ad_id": _coalesce(payload.get("creative_id"), payload.get("ad_id")),
        "ad_name": _coalesce(payload.get("ad_name")),
        "platform": "google",
        "created_time": _coalesce(payload.get("lead_submit_time"), payload.get("submit_time")),
        "field_data": _field_data_from_user_columns(payload.get("user_column_data") or []),
    }


def handle_google_ads_lead(payload: dict[str, Any], db: Session) -> dict[str, Any]:
    validate_google_key(payload)

    lead_id = _coalesce(payload.get("lead_id"))
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")

    is_test = bool(payload.get("is_test"))
    if is_test and not settings.google_ads_accept_test_leads:
        return {"status": "ok", "lead_id": lead_id, "is_test": True, "ingested": False}

    dedup_key = f"{DEDUP_PREFIX}{lead_id}"
    existing_before = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == dedup_key).first()
    if existing_before is None:
        source_tags = ("google", "google_ads_lead")
        if is_test:
            source_tags += ("test_lead",)
        # Never persist the shared secret alongside the lead.
        raw_payload = {k: v for k, v in payload.items() if k != "google_key"}
        _ingest_graph_style_lead(
            db,
            lead=_graph_lead_from_google_payload(payload, dedup_key),
            lead_id=dedup_key,
            owner=_get_default_owner(db),
            raw_payload=raw_payload,
            interaction_subject="Google Ads Lead Form submission",
            source_tags=source_tags,
            fallback_name_prefix="Google Lead",
        )

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == dedup_key).first()
    return {
        "status": "ok",
        "lead_id": lead_id,
        "is_test": is_test,
        "ingested": True,
        "customer_id": str(event.customer_id) if event and event.customer_id else None,
        "deal_id": str(event.deal_id) if event and event.deal_id else None,
        "deduped": existing_before is not None,
    }
