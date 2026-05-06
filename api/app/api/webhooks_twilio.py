from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.whatsapp_ingestion import process_inbound_whatsapp_message

router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


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
    # Twilio sends application/x-www-form-urlencoded.
    form = dict(await request.form())
    _validate_twilio_signature_if_enabled(request, form)

    from_raw = str(form.get("From") or "").strip()
    if not from_raw:
        raise HTTPException(status_code=400, detail="Missing From")

    process_inbound_whatsapp_message(
        db,
        from_phone=from_raw,
        body=str(form.get("Body") or ""),
        provider_message_id=str(form.get("MessageSid") or "").strip() or None,
        profile_name=str(form.get("ProfileName") or "").strip() or None,
        raw_payload=form,
    )

    # Twilio accepts empty 200, but we return minimal TwiML.
    return Response(content="<Response></Response>", media_type="application/xml")
