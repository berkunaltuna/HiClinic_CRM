from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.whatsapp_ingestion import process_inbound_whatsapp_message

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])


def _validate_meta_signature_if_enabled(request: Request, body: bytes) -> None:
    if not settings.whatsapp_validate_signature:
        return

    app_secret = (settings.whatsapp_app_secret or settings.facebook_app_secret or "").strip()
    if not app_secret:
        raise HTTPException(status_code=500, detail="WHATSAPP_APP_SECRET missing; cannot validate webhook")

    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")

    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid Meta webhook signature")


@router.get("")
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
async def receive_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.body()
    _validate_meta_signature_if_enabled(request, body)

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload")

    processed: list[dict[str, Any]] = []

    # WhatsApp Cloud API payload shape:
    # entry[].changes[].value.contacts[] and entry[].changes[].value.messages[]
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            messages = value.get("messages") or []
            contacts = value.get("contacts") or []

            profile_by_wa_id: dict[str, str] = {}
            for contact in contacts:
                wa_id = str(contact.get("wa_id") or "").strip()
                name = str((contact.get("profile") or {}).get("name") or "").strip()
                if wa_id and name:
                    profile_by_wa_id[wa_id] = name

            # Status-only webhook events have no messages; ignore them for lead ingestion.
            for message in messages:
                sender = str(message.get("from") or "").strip()
                if not sender:
                    continue

                message_type = str(message.get("type") or "").strip()
                text_body = ""
                if message_type == "text":
                    text_body = str((message.get("text") or {}).get("body") or "")
                elif message_type:
                    text_body = f"[{message_type} message received]"

                result = process_inbound_whatsapp_message(
                    db,
                    from_phone=sender,
                    body=text_body,
                    provider_message_id=str(message.get("id") or "").strip() or None,
                    profile_name=profile_by_wa_id.get(sender),
                    raw_payload=payload,
                )
                processed.append(result)

    return {"status": "ok", "processed": len(processed), "results": processed}
