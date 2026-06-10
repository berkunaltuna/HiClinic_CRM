from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Interaction, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.interaction import InteractionCreate, InteractionOut
from app.services.audit import record_audit

router = APIRouter(prefix="", tags=["interactions"])


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("/customers/{customer_id}/interactions", response_model=InteractionOut, status_code=201)
def create_interaction(
    customer_id: UUID,
    payload: InteractionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InteractionOut:
    customer = _get_customer(db, customer_id, user)
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
    db.flush()
    action = "note.created" if (payload.subject or "").lower() == "internal note" else "interaction.created"
    record_audit(
        db,
        actor=user,
        action=action,
        entity_type="customer",
        entity_id=customer.id,
        after={
            "interaction_id": str(interaction.id),
            "channel": interaction.channel,
            "direction": interaction.direction,
            "subject": interaction.subject,
            "content": interaction.content,
        },
        metadata={"customer_id": str(customer.id), "customer_name": customer.name},
    )
    db.commit()
    db.refresh(interaction)
    return interaction


@router.get("/customers/{customer_id}/interactions", response_model=list[InteractionOut])
def list_interactions(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InteractionOut]:
    _get_customer(db, customer_id, user)
    return db.query(Interaction).filter(Interaction.customer_id == customer_id).order_by(Interaction.occurred_at.desc()).all()
