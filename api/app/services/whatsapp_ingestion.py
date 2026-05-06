from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Customer, Deal, DealStatus, Interaction, OutboundMessage, User
from app.services.automation import handle_event
from app.services.tags import add_tag_to_customer


def normalise_whatsapp_phone(raw: str | None) -> str:
    """Normalise WhatsApp phone values for storage.

    Meta Cloud API sends the sender in `messages[].from` without a plus sign,
    for example `447700900123`. Twilio sends `whatsapp:+447700900123`.
    The CRM stores E.164-like values with a leading plus sign.
    """
    value = (raw or "").strip()
    if value.lower().startswith("whatsapp:"):
        value = value.split(":", 1)[1].strip()
    value = value.replace(" ", "")

    if value.startswith("+"):
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"+{digits}" if digits else value

    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return value

    if digits.startswith("00"):
        return f"+{digits[2:]}"

    if digits.startswith("0"):
        country = (settings.default_country_code or "+44").strip() or "+44"
        return f"{country}{digits[1:]}"

    # WhatsApp Cloud API normally sends country-code-prefixed numbers.
    return f"+{digits}"


def get_default_whatsapp_owner(db: Session) -> User:
    configured_id = (getattr(settings, "whatsapp_default_owner_user_id", None) or "").strip()
    if configured_id:
        try:
            owner = db.get(User, UUID(configured_id))
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail="WHATSAPP_DEFAULT_OWNER_USER_ID is invalid") from exc
        if owner is None:
            raise HTTPException(status_code=500, detail="Configured WhatsApp default owner does not exist")
        return owner

    # Same fallback as the existing inbound webhook pattern: use latest user.
    user = db.query(User).order_by(User.created_at.desc()).first()
    if user is None:
        raise HTTPException(status_code=400, detail="No users exist yet; create an account first")
    return user


def _ensure_open_deal(db: Session, *, customer: Customer, owner: User) -> Deal:
    existing = (
        db.query(Deal)
        .filter(Deal.customer_id == customer.id, Deal.status == DealStatus.open)
        .order_by(Deal.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing

    deal = Deal(customer_id=customer.id, owner_user_id=owner.id, amount=0, status=DealStatus.open)
    db.add(deal)
    db.flush()
    return deal


def process_inbound_whatsapp_message(
    db: Session,
    *,
    from_phone: str,
    body: str | None,
    provider_message_id: str | None = None,
    profile_name: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create/update CRM records from an inbound WhatsApp message.

    This is shared by the native Meta WhatsApp Cloud API webhook and the older
    Twilio WhatsApp webhook, so both ingestion paths behave consistently.
    """
    phone = normalise_whatsapp_phone(from_phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Missing WhatsApp sender phone")

    message_id = (provider_message_id or "").strip() or None
    if message_id:
        existing_interaction = (
            db.query(Interaction)
            .filter(Interaction.provider_message_id == message_id)
            .first()
        )
        if existing_interaction is not None:
            return {
                "status": "ok",
                "deduped": True,
                "customer_id": str(existing_interaction.customer_id),
                "interaction_id": str(existing_interaction.id),
            }

    owner = get_default_whatsapp_owner(db)

    customer = db.query(Customer).filter(Customer.phone == phone).first()
    is_new_customer = customer is None
    if customer is None:
        customer = Customer(
            owner_user_id=owner.id,
            name=(profile_name or "").strip() or f"WhatsApp Lead {phone}",
            phone=phone,
            can_contact=True,
            language="en" if phone.startswith("+44") else None,
        )
        db.add(customer)
        db.flush()
    else:
        clean_name = (profile_name or "").strip()
        if clean_name and (not customer.name or customer.name.startswith("WhatsApp Lead")):
            customer.name = clean_name

    deal = _ensure_open_deal(db, customer=customer, owner=owner)

    # Cancel any scheduled follow-up that should stop when the lead replies.
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
        owner_user_id=customer.owner_user_id,
        channel="whatsapp",
        direction="inbound",
        content=body or "",
        provider_message_id=message_id,
    )
    db.add(interaction)
    db.flush()

    add_tag_to_customer(db, customer=customer, tag_name="whatsapp")
    if is_new_customer:
        add_tag_to_customer(db, customer=customer, tag_name="new_lead")

    message_lower = (body or "").lower()
    for keyword, tag_name in (settings.keyword_tags or {}).items():
        if keyword and keyword.lower() in message_lower:
            add_tag_to_customer(db, customer=customer, tag_name=tag_name)

    if customer.stage == "new":
        customer.stage = "engaged"

    db.commit()
    db.refresh(customer)
    db.refresh(interaction)
    db.refresh(deal)

    created_messages = handle_event(
        db,
        owner_user_id=customer.owner_user_id,
        event="message.received",
        customer_id=customer.id,
        context={
            "channel": "whatsapp",
            "is_new_customer": is_new_customer,
            "message_body": body or "",
            "customer_phone": phone,
            "customer_stage": customer.stage,
            "customer_tags": customer.tag_names,
            "provider_message_id": message_id,
            "raw_payload": raw_payload or {},
        },
    )

    db.refresh(customer)

    return {
        "status": "ok",
        "deduped": False,
        "is_new_customer": is_new_customer,
        "customer_id": str(customer.id),
        "deal_id": str(deal.id),
        "interaction_id": str(interaction.id),
        "queued_messages": len(created_messages),
    }
