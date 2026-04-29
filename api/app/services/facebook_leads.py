from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
import sqlalchemy as sa

from app.core.config import settings
from app.db.models import Customer, Deal, DealStatus, FacebookLeadEvent, Interaction, User
from app.services.tags import add_tag_to_customer

GRAPH_API_BASE = "https://graph.facebook.com"


def _get_default_owner(db: Session) -> User:
    configured_id = (settings.facebook_default_owner_user_id or "").strip()
    if configured_id:
        try:
            owner = db.get(User, UUID(configured_id))
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail="FACEBOOK_DEFAULT_OWNER_USER_ID is invalid") from exc
        if owner is None:
            raise HTTPException(status_code=500, detail="Configured Facebook default owner does not exist")
        return owner

    user = db.query(User).order_by(User.created_at.desc()).first()
    if user is None:
        raise HTTPException(status_code=400, detail="No users exist yet; create an account first")
    return user


def validate_meta_signature_if_enabled(request: Request, body: bytes) -> None:
    if not settings.facebook_validate_signature:
        return

    app_secret = (settings.facebook_app_secret or "").strip()
    if not app_secret:
        raise HTTPException(status_code=500, detail="FACEBOOK_APP_SECRET missing; cannot validate webhook")

    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")

    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid Meta webhook signature")


async def fetch_facebook_lead(lead_id: str) -> dict[str, Any]:
    token = (settings.facebook_page_access_token or "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="FACEBOOK_PAGE_ACCESS_TOKEN missing")

    version = (settings.facebook_graph_api_version or "v23.0").strip()
    url = f"{GRAPH_API_BASE}/{version}/{lead_id}"
    params = {
        "access_token": token,
        "fields": (
            "id,created_time,ad_id,ad_name,adgroup_id,adgroup_name,"
            "campaign_id,campaign_name,form_id,page_id,field_data,platform"
        ),
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Facebook lead retrieval failed: {exc.response.text}",
            ) from exc
        return resp.json()


def _extract_field(field_data: list[dict[str, Any]], *names: str) -> str | None:
    wanted = {n.lower() for n in names}
    for item in field_data or []:
        key = str(item.get("name") or "").lower()
        if key not in wanted:
            continue
        values = item.get("values") or []
        if not values:
            return None
        first = values[0]
        if isinstance(first, dict):
            return json.dumps(first, ensure_ascii=False)
        return str(first)
    return None


def _normalise_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None

    is_plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if is_plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]

    country = (settings.default_country_code or "+44").strip()
    if digits.startswith("0"):
        digits = digits[1:]
    return f"{country}{digits}"


def _find_existing_customer(db: Session, owner_user_id, email: str | None, phone: str | None) -> Customer | None:
    base = db.query(Customer).filter(Customer.owner_user_id == owner_user_id)
    if phone:
        existing = base.filter(Customer.phone == phone).first()
        if existing is not None:
            return existing
    if email:
        existing = base.filter(Customer.email == email).first()
        if existing is not None:
            return existing
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coalesce(*values: Any) -> str | None:
    for value in values:
        text = _as_str(value)
        if text:
            return text
    return None


def _build_field_data_from_make_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    existing = payload.get("field_data")
    if isinstance(existing, list) and existing:
        return existing

    raw = payload.get("raw")
    if isinstance(raw, dict):
        raw_field_data = raw.get("field_data")
        if isinstance(raw_field_data, list) and raw_field_data:
            return raw_field_data
        raw_fields = raw.get("fields")
        if isinstance(raw_fields, dict):
            built: list[dict[str, Any]] = []
            for key, value in raw_fields.items():
                built.append({"name": str(key), "values": [value] if not isinstance(value, list) else value})
            if built:
                return built

    mapping = {
        "full_name": _coalesce(payload.get("full_name"), payload.get("name"), payload.get("customer_name")),
        "email": _coalesce(payload.get("email"), payload.get("email_address")),
        "phone_number": _coalesce(payload.get("phone"), payload.get("phone_number"), payload.get("mobile")),
        "company_name": _coalesce(payload.get("company"), payload.get("company_name")),
    }
    built = [
        {"name": key, "values": [value]}
        for key, value in mapping.items()
        if value
    ]
    return built


def _graph_lead_from_make_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw")
    if isinstance(raw, dict):
        lead = dict(raw)
    else:
        lead = {}

    lead.setdefault("id", _coalesce(payload.get("lead_id"), payload.get("leadgen_id"), payload.get("id")))
    lead.setdefault("page_id", _coalesce(payload.get("page_id"), payload.get("page")))
    lead.setdefault("form_id", _coalesce(payload.get("form_id")))
    lead.setdefault("campaign_id", _coalesce(payload.get("campaign_id")))
    lead.setdefault("campaign_name", _coalesce(payload.get("campaign_name")))
    lead.setdefault("adgroup_id", _coalesce(payload.get("adset_id"), payload.get("adgroup_id")))
    lead.setdefault("adgroup_name", _coalesce(payload.get("adset_name"), payload.get("adgroup_name")))
    lead.setdefault("ad_id", _coalesce(payload.get("ad_id")))
    lead.setdefault("ad_name", _coalesce(payload.get("ad_name")))
    lead.setdefault("platform", _coalesce(payload.get("platform"), "facebook"))
    lead["field_data"] = _build_field_data_from_make_payload(payload)
    return lead


def _ingest_graph_style_lead(
    db: Session,
    *,
    lead: dict[str, Any],
    lead_id: str,
    owner: User,
    raw_payload: dict[str, Any],
    interaction_subject: str,
) -> None:
    existing_event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == lead_id).first()
    if existing_event is not None:
        return

    field_data = lead.get("field_data") or []

    full_name = _extract_field(field_data, "full_name", "name")
    email = _extract_field(field_data, "email")
    phone = _normalise_phone(_extract_field(field_data, "phone_number", "phone"))
    company = _extract_field(field_data, "company_name", "company")

    customer = _find_existing_customer(db, owner.id, email=email, phone=phone)
    is_new_customer = customer is None
    if customer is None:
        customer = Customer(
            owner_user_id=owner.id,
            name=full_name or phone or email or f"Facebook Lead {lead_id}",
            email=email,
            phone=phone,
            company=company,
            can_contact=True,
            language="en",
        )
        db.add(customer)
        db.flush()
    else:
        if full_name and (not customer.name or customer.name.startswith("Facebook Lead")):
            customer.name = full_name
        if email and not customer.email:
            customer.email = email
        if phone and not customer.phone:
            customer.phone = phone
        if company and not customer.company:
            customer.company = company

    existing_open_deal = (
        db.query(Deal)
        .filter(Deal.customer_id == customer.id, Deal.status == DealStatus.open)
        .order_by(Deal.created_at.desc())
        .first()
    )
    if existing_open_deal is None:
        deal = Deal(customer_id=customer.id, owner_user_id=owner.id, amount=0, status=DealStatus.open)
        db.add(deal)
        db.flush()
    else:
        deal = existing_open_deal

    event = FacebookLeadEvent(
        owner_user_id=owner.id,
        leadgen_id=lead_id,
        page_id=_coalesce(lead.get("page_id")),
        form_id=_coalesce(lead.get("form_id")),
        campaign_id=_coalesce(lead.get("campaign_id")),
        adset_id=_coalesce(lead.get("adgroup_id"), lead.get("adset_id")),
        ad_id=_coalesce(lead.get("ad_id")),
        customer_id=customer.id,
        deal_id=deal.id if deal is not None else None,
        raw_payload=raw_payload,
    )
    db.add(event)

    summary = {
        "leadgen_id": lead_id,
        "campaign_name": lead.get("campaign_name"),
        "adset_name": lead.get("adgroup_name") or lead.get("adset_name"),
        "ad_name": lead.get("ad_name"),
        "form_id": lead.get("form_id"),
        "page_id": lead.get("page_id"),
        "platform": lead.get("platform"),
    }
    interaction = Interaction(
        customer_id=customer.id,
        owner_user_id=owner.id,
        channel="email",
        direction="inbound",
        subject=interaction_subject,
        content=json.dumps(summary, ensure_ascii=False),
        provider_message_id=lead_id,
    )
    db.add(interaction)

    add_tag_to_customer(db, customer=customer, tag_name="facebook")
    add_tag_to_customer(db, customer=customer, tag_name="facebook_lead")
    if is_new_customer:
        add_tag_to_customer(db, customer=customer, tag_name="new_lead")

    if customer.stage == "new":
        customer.stage = "contacted"

    db.commit()


async def handle_facebook_webhook(payload: dict[str, Any], db: Session) -> None:
    if payload.get("object") not in (None, "page"):
        return

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue

            value = change.get("value") or {}
            lead_id = str(value.get("leadgen_id") or "").strip()
            if not lead_id:
                continue

            owner = _get_default_owner(db)
            lead = await fetch_facebook_lead(lead_id)
            _ingest_graph_style_lead(
                db,
                lead=lead,
                lead_id=lead_id,
                owner=owner,
                raw_payload=lead,
                interaction_subject="Facebook Lead Form submission",
            )


async def handle_make_facebook_lead(payload: dict[str, Any], db: Session) -> dict[str, Any]:
    lead_id = _coalesce(payload.get("lead_id"), payload.get("leadgen_id"), payload.get("id"))
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id or leadgen_id is required")

    existing_before = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == lead_id).first()
    if existing_before is None:
        owner = _get_default_owner(db)
        lead = _graph_lead_from_make_payload(payload)
        _ingest_graph_style_lead(
            db,
            lead=lead,
            lead_id=lead_id,
            owner=owner,
            raw_payload=payload.get("raw") if isinstance(payload.get("raw"), dict) else payload,
            interaction_subject="Facebook Lead Form submission",
        )

    event = db.query(FacebookLeadEvent).filter(FacebookLeadEvent.leadgen_id == lead_id).first()
    return {
        "status": "ok",
        "leadgen_id": lead_id,
        "customer_id": str(event.customer_id) if event and event.customer_id else None,
        "deal_id": str(event.deal_id) if event and event.deal_id else None,
        "deduped": existing_before is not None,
    }
