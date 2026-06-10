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
from app.db.models import Customer, Deal, DealStatus, FacebookLeadEvent, Interaction, OutboundMessage, User
from app.services.tags import add_tag_to_customer

GRAPH_API_BASE = "https://graph.facebook.com"

TREATMENT_TAG_MAP = {
    # Human-readable Meta values
    "Hair Transplant": "Hair Transplant",
    "Facial Aesthetics (Face Lift ect))": "Facial Aesthetics",
    "Eyelid surgery (blepharoplasty)": "Eyelid Surgery",
    "Body Contouring (Tummy Tuck, BBL, Lipo)": "Body Contouring",
    "Breast Aesthetic Surgery": "Breast Aesthetic Surgery",
    # Make/Facebook slug values currently sent by the Make scenario
    "hair_transplant": "Hair Transplant",
    "facial_aesthetics_(face_lift_ect))": "Facial Aesthetics",
    "facial_aesthetics_face_lift_ect": "Facial Aesthetics",
    "eyelid_surgery_(blepharoplasty)": "Eyelid Surgery",
    "body_contouring_(tummy_tuck,_bbl,_lipo)": "Body Contouring",
    "body_contouring_tummy_tuck_bbl_lipo": "Body Contouring",
    "breast_aesthetic_surgery": "Breast Aesthetic Surgery",
}

CONSULTATION_DAY_TAG_MAP = {
    "saturday,_27th_june_2026": "Saturday 27 June",
    "saturday_27th_june_2026": "Saturday 27 June",
    "sunday,_28th_june_2026": "Sunday 28 June",
    "sunday_28th_june_2026": "Sunday 28 June",
    "either": "Either Day",
    "either_day": "Either Day",
}

SEMINAR_PREFERENCE_TAG_MAP = {
    "one_to_one_consultation": "One-to-One Consultation",
    "yes,_i_am_interested_in_learning_more_about_procedures": "Seminar Interested",
    "yes_i_am_interested_in_learning_more_about_procedures": "Seminar Interested",
}


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


def _field_name_key(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _extract_field_fuzzy(field_data: list[dict[str, Any]], *names: str) -> str | None:
    wanted = {_field_name_key(n) for n in names}
    for item in field_data or []:
        key = _field_name_key(str(item.get("name") or ""))
        if key not in wanted:
            continue
        values = item.get("values") or []
        if not values:
            return None
        # Meta can return checkbox answers as multiple values. Keep them readable.
        cleaned: list[str] = []
        for value in values:
            if isinstance(value, dict):
                cleaned.append(json.dumps(value, ensure_ascii=False))
            else:
                text = str(value).strip()
                if text:
                    cleaned.append(text)
        return ", ".join(cleaned) if cleaned else None
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


def _normalise_answer_key(value: Any) -> str:
    text = str(value or "").strip()
    # Make commonly sends values like sunday,_28th_june_2026. Keep commas and
    # brackets where they are meaningful, but also collapse spaces for matching.
    return text.replace(" ", "_").lower()


def _split_answer_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    # Checkbox answers may arrive as a JSON array string or as comma/newline separated text.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    except Exception:
        pass
    if "\n" in text:
        return [part.strip() for part in text.splitlines() if part.strip()]
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [text]


def _map_answer_to_tag(value: Any, mapping: dict[str, str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return mapping.get(text) or mapping.get(_normalise_answer_key(text))


def _collect_form_tags(treatment_interest: Any, preferred_consultation_day: Any, seminar_preference: Any) -> list[str]:
    tags: list[str] = []
    for value in _split_answer_values(treatment_interest):
        tag = _map_answer_to_tag(value, TREATMENT_TAG_MAP)
        if tag:
            tags.append(tag)
    for value in _split_answer_values(preferred_consultation_day):
        tag = _map_answer_to_tag(value, CONSULTATION_DAY_TAG_MAP)
        if tag:
            tags.append(tag)
    for value in _split_answer_values(seminar_preference):
        tag = _map_answer_to_tag(value, SEMINAR_PREFERENCE_TAG_MAP)
        if tag:
            tags.append(tag)
    return list(dict.fromkeys(tags))



def _clean_tag_fragment(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = " ".join(text.replace("_", " ").split())
    return text[:80]

def _attribution_from_lead(lead: dict[str, Any]) -> dict[str, str | None]:
    return {
        "lead_source": _coalesce(lead.get("platform"), "facebook"),
        "form_id": _coalesce(lead.get("form_id")),
        "form_name": _coalesce(lead.get("form_name")),
        "campaign_id": _coalesce(lead.get("campaign_id")),
        "campaign_name": _coalesce(lead.get("campaign_name")),
        "adset_id": _coalesce(lead.get("adgroup_id"), lead.get("adset_id")),
        "adset_name": _coalesce(lead.get("adgroup_name"), lead.get("adset_name")),
        "ad_id": _coalesce(lead.get("ad_id")),
        "ad_name": _coalesce(lead.get("ad_name")),
    }

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
        "treatment_interest": _coalesce(
            payload.get("treatment_interest"),
            payload.get("treatment"),
            payload.get("treatments"),
            payload.get("which_treatment_are_you_interested_in"),
        ),
        "preferred_consultation_day": _coalesce(
            payload.get("preferred_consultation_day"),
            payload.get("consultation_day"),
            payload.get("preferred_day"),
        ),
        "seminar_preference": _coalesce(
            payload.get("seminar_preference"),
            payload.get("seminar"),
        ),
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
    lead.setdefault("form_name", _coalesce(payload.get("form_name")))
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

    full_name = _extract_field_fuzzy(field_data, "full_name", "full name", "name")
    email = _extract_field_fuzzy(field_data, "email", "email address")
    phone = _normalise_phone(_extract_field_fuzzy(field_data, "phone_number", "phone number", "phone", "mobile"))
    company = _extract_field_fuzzy(field_data, "company_name", "company name", "company")

    treatment_interest = _extract_field_fuzzy(
        field_data,
        "which treatment are you interested in",
        "treatment_interest",
        "treatment interest",
        "treatments",
        "treatment",
    )
    preferred_consultation_day = _extract_field_fuzzy(
        field_data,
        "preferred consultation day",
        "consultation day",
        "preferred_day",
        "preferred day",
    )
    seminar_preference = _extract_field_fuzzy(
        field_data,
        "would you like to attend the seminar",
        "seminar",
        "seminar_preference",
        "seminar preference",
    )

    form_tag_names = _collect_form_tags(
        treatment_interest,
        preferred_consultation_day,
        seminar_preference,
    )
    attribution = _attribution_from_lead(lead)

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
            lead_source=attribution.get("lead_source"),
            form_id=attribution.get("form_id"),
            form_name=attribution.get("form_name"),
            campaign_id=attribution.get("campaign_id"),
            campaign_name=attribution.get("campaign_name"),
            adset_id=attribution.get("adset_id"),
            adset_name=attribution.get("adset_name"),
            ad_id=attribution.get("ad_id"),
            ad_name=attribution.get("ad_name"),
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
    for attr_key, attr_value in attribution.items():
        if attr_value and not getattr(customer, attr_key, None):
            setattr(customer, attr_key, attr_value)

    existing_open_deal = (
        db.query(Deal)
        .filter(Deal.customer_id == customer.id, Deal.status == DealStatus.open)
        .order_by(Deal.created_at.desc())
        .first()
    )
    if existing_open_deal is None:
        deal = Deal(
            customer_id=customer.id,
            owner_user_id=owner.id,
            amount=0,
            status=DealStatus.open,
            treatment_interest=treatment_interest,
            preferred_consultation_day=preferred_consultation_day,
            seminar_preference=seminar_preference,
        )
        db.add(deal)
        db.flush()
    else:
        deal = existing_open_deal
        if treatment_interest and not deal.treatment_interest:
            deal.treatment_interest = treatment_interest
        if preferred_consultation_day and not deal.preferred_consultation_day:
            deal.preferred_consultation_day = preferred_consultation_day
        if seminar_preference and not deal.seminar_preference:
            deal.seminar_preference = seminar_preference

    event = FacebookLeadEvent(
        owner_user_id=owner.id,
        leadgen_id=lead_id,
        page_id=_coalesce(lead.get("page_id")),
        form_id=_coalesce(lead.get("form_id")),
        campaign_id=_coalesce(lead.get("campaign_id")),
        campaign_name=_coalesce(lead.get("campaign_name")),
        adset_id=_coalesce(lead.get("adgroup_id"), lead.get("adset_id")),
        adset_name=_coalesce(lead.get("adgroup_name"), lead.get("adset_name")),
        ad_id=_coalesce(lead.get("ad_id")),
        ad_name=_coalesce(lead.get("ad_name")),
        form_name=_coalesce(lead.get("form_name")),
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
        "treatment_interest": treatment_interest,
        "preferred_consultation_day": preferred_consultation_day,
        "seminar_preference": seminar_preference,
    }
    # Treat new Facebook/Make lead submissions as inbound activity. This also
    # cancels any queued outreach marked cancel_on_inbound for returning leads.
    db.query(OutboundMessage).filter(
        OutboundMessage.customer_id == customer.id,
        OutboundMessage.status == "queued",
        OutboundMessage.cancel_on_inbound.is_(True),
    ).update(
        {"status": "cancelled", "cancelled_at": sa.text("now()")},
        synchronize_session=False,
    )

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
    if treatment_interest:
        add_tag_to_customer(db, customer=customer, tag_name=f"interest:{treatment_interest}")
    if preferred_consultation_day:
        add_tag_to_customer(db, customer=customer, tag_name=f"day:{preferred_consultation_day}")
    if seminar_preference:
        add_tag_to_customer(db, customer=customer, tag_name=f"seminar:{seminar_preference}")
    for prefix, attr_key in [("form", "form_name"), ("campaign", "campaign_name"), ("adset", "adset_name"), ("ad", "ad_name")]:
        fragment = _clean_tag_fragment(attribution.get(attr_key))
        if fragment:
            add_tag_to_customer(db, customer=customer, tag_name=f"{prefix}:{fragment}")

    for tag_name in form_tag_names:
        add_tag_to_customer(db, customer=customer, tag_name=tag_name)

    # Facebook/Make lead ingestion should never move a lead to Contacted.
    # New customers stay in the New stage until a user explicitly changes them.
    if is_new_customer:
        customer.stage = "new"

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
