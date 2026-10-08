from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.google_ads_leads import handle_google_ads_lead

router = APIRouter(prefix="/webhooks/google", tags=["webhooks"])


@router.post("/ads-lead")
async def receive_google_ads_lead(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object payload")

    return handle_google_ads_lead(payload=payload, db=db)
