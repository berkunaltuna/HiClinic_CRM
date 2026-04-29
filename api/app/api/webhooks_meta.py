from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.facebook_leads import (
    handle_facebook_webhook,
    validate_meta_signature_if_enabled,
)


router = APIRouter(prefix="/webhooks/meta", tags=["webhooks"])


@router.get("/facebook")
def verify_facebook_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.facebook_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/facebook")
async def receive_facebook_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.body()
    validate_meta_signature_if_enabled(request, body)
    payload = json.loads(body.decode("utf-8") or "{}")
    await handle_facebook_webhook(payload=payload, db=db)
    return {"status": "ok"}
