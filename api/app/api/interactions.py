from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Interaction, User
from app.db.session import get_db
from app.schemas.interaction import InteractionCreate, InteractionOut

from uuid import UUID

router = APIRouter(prefix="", tags=["interactions"])


def _get_owned_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("/customers/{customer_id}/interactions", response_model=InteractionOut, status_code=201)
def create_interaction(
    customer_id: UUID,
    payload: InteractionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InteractionOut:
    customer = _get_owned_customer(db, customer_id, user)
    occurred_at = payload.occurred_at or datetime.now(tz=timezone.utc)
    interaction = Interaction(
        customer_id=customer.id,
        owner_user_id=user.id,
        channel=payload.channel,
        direction=payload.direction,
        occurred_at=occurred_at,
        content=payload.content,
        subject=payload.subject,
        provider_message_id=payload.provider_message_id,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


@router.get("/customers/{customer_id}/interactions", response_model=list[InteractionOut])
def list_interactions(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InteractionOut]:
    _get_owned_customer(db, customer_id, user)
    return (
        db.query(Interaction)
        .filter(Interaction.customer_id == customer_id, Interaction.owner_user_id == user.id)
        .order_by(Interaction.occurred_at.desc())
        .all()
    )
