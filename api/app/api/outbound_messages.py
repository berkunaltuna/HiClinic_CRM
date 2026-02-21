from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, OutboundMessage, User
from app.db.session import get_db
from app.schemas.outbound_message import OutboundMessageCreate, OutboundMessageOut


router = APIRouter(prefix="/outbound-messages", tags=["outbound-messages"])


@router.get("", response_model=list[OutboundMessageOut])
def list_outbound_messages(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OutboundMessageOut]:
    # For minimal CRM: show only the current user's queued/sent messages across their customers.
    return (
        db.query(OutboundMessage)
        .filter(OutboundMessage.owner_user_id == user.id)
        .order_by(OutboundMessage.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("", response_model=OutboundMessageOut, status_code=status.HTTP_201_CREATED)
def create_outbound_message(
    payload: OutboundMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OutboundMessageOut:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.owner_user_id != user.id:
        # keep tenant isolation simple
        raise HTTPException(status_code=403, detail="Forbidden")

    msg = OutboundMessage(
        owner_user_id=user.id,
        customer_id=payload.customer_id,
        channel=payload.channel,
        status="queued",
        template_id=payload.template_id,
        body=payload.body,
        variables=payload.variables,
        not_before_at=payload.not_before_at,
        cancel_on_inbound=payload.cancel_on_inbound,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/{message_id}", response_model=OutboundMessageOut)
def get_outbound_message(
    message_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OutboundMessageOut:
    msg = db.get(OutboundMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Outbound message not found")
    if msg.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return msg
