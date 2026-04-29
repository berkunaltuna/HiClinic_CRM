from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, OutcomeEvent, OutcomeType, User
from app.db.session import get_db
from app.schemas.outcome import OutcomeEventCreate, OutcomeEventOut


router = APIRouter(prefix="/outcomes", tags=["outcomes"])


@router.get("", response_model=list[OutcomeEventOut])
def list_outcomes(
    customer_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OutcomeEventOut]:
    q = db.query(OutcomeEvent).filter(OutcomeEvent.owner_user_id == user.id)
    if customer_id is not None:
        q = q.filter(OutcomeEvent.customer_id == customer_id)
    return q.order_by(OutcomeEvent.occurred_at.desc()).limit(500).all()


@router.post("", response_model=OutcomeEventOut, status_code=status.HTTP_201_CREATED)
def create_outcome(
    payload: OutcomeEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OutcomeEventOut:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        outcome_type = OutcomeType(payload.type)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid outcome type")

    ev = OutcomeEvent(
        owner_user_id=user.id,
        customer_id=payload.customer_id,
        type=outcome_type,
        amount=payload.amount,
        notes=payload.notes,
        meta=payload.metadata,
        occurred_at=payload.occurred_at or datetime.utcnow(),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
