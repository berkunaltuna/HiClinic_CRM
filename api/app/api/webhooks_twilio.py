from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Customer, Interaction, OutboundMessage, User
from app.db.session import get_db
from app.services.automation import handle_event
from app.services.tags import add_tag_to_customer


router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


def _normalise_phone_for_storage(s: str) -> str:
    """Normalise to E.164-like string for storage.

    Twilio WhatsApp inbound uses 'whatsapp:+447...' in the From field.
    We store '+447...' (no 'whatsapp:' prefix) so outbound code can add it later.
    """
    v = (s or "").strip()
    if v.lower().startswith("whatsapp:"):
        v = v.split(":", 1)[1].strip()
    v = v.replace(" ", "")

    if v.startswith("+"):
        return v

    # crude fallback for local numbers: strip non-digits and prefix default country code
    digits = "".join(ch for ch in v if ch.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    return f"{settings.default_country_code}{digits}"


def _get_default_owner(db: Session) -> User:
    # Pick a deterministic owner for unauthenticated inbound webhooks.
    # We prefer the most recently created user so that in fresh/self-hosted
    # setups (and tests) the "primary" account created during setup becomes
    # the default owner. In multi-user deployments you may want to replace
    # this with an explicit DEFAULT_OWNER_USER_ID/EMAIL setting.
    user = db.query(User).order_by(User.created_at.desc()).first()
    if user is None:
        raise HTTPException(status_code=400, detail="No users exist yet; create an account first")
    return user


def _validate_twilio_signature_if_enabled(request: Request, form: dict[str, Any]) -> None:
    if not settings.twilio_validate_signature:
        return

    if not settings.twilio_auth_token:
        raise HTTPException(status_code=500, detail="TWILIO_AUTH_TOKEN missing; cannot validate webhook")
    if not settings.twilio_webhook_base_url:
        raise HTTPException(status_code=500, detail="TWILIO_WEBHOOK_BASE_URL missing; cannot validate webhook")

    try:
        from twilio.request_validator import RequestValidator
    except Exception:
        raise HTTPException(status_code=500, detail="twilio package missing in API container")

    # Twilio signs the exact URL it posts to.
    # We use the configured public base URL + the request path.
    url = settings.twilio_webhook_base_url.rstrip("/") + str(request.url.path)
    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing X-Twilio-Signature header")

    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(url, form, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/whatsapp")
async def twilio_whatsapp_inbound(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    # Twilio sends application/x-www-form-urlencoded
    form = dict(await request.form())
    _validate_twilio_signature_if_enabled(request, form)

    from_raw = str(form.get("From") or "").strip()
    body = str(form.get("Body") or "")
    message_sid = str(form.get("MessageSid") or "").strip() or None
    profile_name = str(form.get("ProfileName") or "").strip() or None

    if not from_raw:
        raise HTTPException(status_code=400, detail="Missing From")

    phone = _normalise_phone_for_storage(from_raw)
    owner = _get_default_owner(db)

    customer = db.query(Customer).filter(Customer.phone == phone).first()
    is_new_customer = False
    if customer is None:
        is_new_customer = True
        customer = Customer(
            owner_user_id=owner.id,
            name=profile_name or f"WhatsApp Lead {phone}",
            phone=phone,
            can_contact=True,
            language="en" if phone.startswith("+44") else None,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    # Phase 4C: cancel any queued messages that should be cancelled on inbound reply
    db.query(OutboundMessage).filter(
        OutboundMessage.customer_id == customer.id,
        OutboundMessage.status == "queued",
        OutboundMessage.cancel_on_inbound.is_(True),
    ).update(
        {"status": "cancelled", "cancelled_at": sa.text("now()")},
        synchronize_session=False,
    )

    # Record inbound interaction
    interaction = Interaction(
        customer_id=customer.id,
        owner_user_id=customer.owner_user_id,
        channel="whatsapp",
        direction="inbound",
        content=body,
        provider_message_id=message_sid,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    # Phase 4B: auto tagging
    add_tag_to_customer(db, customer=customer, tag_name="whatsapp")
    if is_new_customer:
        add_tag_to_customer(db, customer=customer, tag_name="new_lead")
    # Keyword based tags
    msg_l = (body or "").lower()
    for kw, tag in (settings.keyword_tags or {}).items():
        if kw and kw.lower() in msg_l:
            add_tag_to_customer(db, customer=customer, tag_name=tag)

    # Basic funnel stage progression: new -> engaged on first inbound.
    if customer.stage == "new":
        customer.stage = "engaged"
    db.commit()

    # Phase 4C: automation hooks
    handle_event(
        db,
        owner_user_id=customer.owner_user_id,
        event="message.received",
        customer_id=customer.id,
        context={
            "channel": "whatsapp",
            "is_new_customer": is_new_customer,
            "message_body": body,
            "customer_phone": phone,
            "customer_stage": customer.stage,
            "customer_tags": customer.tag_names,
        },
    )

    # Twilio accepts empty 200, but we return minimal TwiML.
    return Response(content="<Response></Response>", media_type="application/xml")
