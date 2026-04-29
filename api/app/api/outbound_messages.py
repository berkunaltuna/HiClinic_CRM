from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import get_current_user
from app.db.models import Customer, OutboundMessage, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.outbound_message import OutboundMessageCreate, OutboundMessageOut

router = APIRouter(prefix="/outbound-messages", tags=["outbound-messages"])


@router.get("", response_model=list[OutboundMessageOut])
def list_outbound_messages(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OutboundMessageOut]:
    q = db.query(OutboundMessage).options(joinedload(OutboundMessage.customer), joinedload(OutboundMessage.template))
    if not settings.share_customers_across_users:
        q = q.filter(OutboundMessage.owner_user_id == user.id)
    return q.order_by(OutboundMessage.created_at.desc()).limit(200).all()


@router.post("", response_model=OutboundMessageOut, status_code=status.HTTP_201_CREATED)
def create_outbound_message(
    payload: OutboundMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OutboundMessageOut:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

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
    q = db.query(OutboundMessage).options(joinedload(OutboundMessage.customer), joinedload(OutboundMessage.template)).filter(OutboundMessage.id == message_id)
    if not settings.share_customers_across_users:
        q = q.filter(OutboundMessage.owner_user_id == user.id)
    msg = q.first()
    if msg is None:
        raise HTTPException(status_code=404, detail="Outbound message not found")
    return msg
