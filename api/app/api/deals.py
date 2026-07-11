from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Deal, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.deal import DealCreate, DealOut, DealUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="", tags=["deals"])


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _get_deal(db: Session, deal_id: UUID, user: User) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not settings.share_customers_across_users and deal.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.post("/customers/{customer_id}/deals", response_model=DealOut, status_code=201)
def create_deal(
    customer_id: UUID,
    payload: DealCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DealOut:
    customer = _get_customer(db, customer_id, user)
    deal = Deal(
        customer_id=customer.id,
        owner_user_id=user.id,
        amount=payload.amount,
        quote_amount=payload.quote_amount,
        status=payload.status,
        treatment_interest=payload.treatment_interest,
        preferred_consultation_day=payload.preferred_consultation_day,
        seminar_preference=payload.seminar_preference,
        event_id=payload.event_id,
        lost_reason=payload.lost_reason,
    )
    db.add(deal)
    db.flush()
    record_audit(db, actor=user, action="deal.created", entity_type="deal", entity_id=deal.id, after={"customer_id": str(customer.id), "status": deal.status, "amount": float(deal.amount or 0), "quote_amount": float(deal.quote_amount) if deal.quote_amount is not None else None})
    db.commit()
    db.refresh(deal)
    return deal


@router.get("/customers/{customer_id}/deals", response_model=list[DealOut])
def list_deals(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DealOut]:
    _get_customer(db, customer_id, user)
    return db.query(Deal).filter(Deal.customer_id == customer_id).order_by(Deal.id.asc()).all()


@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DealOut:
    deal = _get_deal(db, deal_id, user)
    before = {"status": deal.status, "amount": float(deal.amount or 0), "quote_amount": float(deal.quote_amount) if deal.quote_amount is not None else None, "treatment_interest": deal.treatment_interest, "preferred_consultation_day": deal.preferred_consultation_day, "seminar_preference": deal.seminar_preference, "event_id": str(deal.event_id) if deal.event_id else None, "lost_reason": deal.lost_reason}
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(deal, key, value)
    db.add(deal)
    after = {"status": deal.status, "amount": float(deal.amount or 0), "quote_amount": float(deal.quote_amount) if deal.quote_amount is not None else None, "treatment_interest": deal.treatment_interest, "preferred_consultation_day": deal.preferred_consultation_day, "seminar_preference": deal.seminar_preference, "event_id": str(deal.event_id) if deal.event_id else None, "lost_reason": deal.lost_reason}
    record_audit(db, actor=user, action="deal.updated", entity_type="deal", entity_id=deal.id, before=before, after=after, metadata={"customer_id": str(deal.customer_id)})
    db.commit()
    db.refresh(deal)
    return deal
