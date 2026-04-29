from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.facebook_leads import handle_make_facebook_lead

router = APIRouter(prefix="/webhooks/make", tags=["webhooks"])


def _validate_make_secret_if_configured(request: Request) -> None:
    expected = (settings.make_webhook_secret or "").strip()
    if not expected:
        return
    actual = request.headers.get("X-Make-Secret", "").strip()
    if actual != expected:
        raise HTTPException(status_code=403, detail="Invalid Make webhook secret")


@router.post("/facebook-lead")
async def receive_make_facebook_lead(
    request: Request,
    db: Session = Depends(get_db),
):
    _validate_make_secret_if_configured(request)
    try:
        payload = await request.json()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload")

    result = await handle_make_facebook_lead(payload=payload, db=db)
    return result
