from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Deal, User
from app.db.session import get_db
from app.schemas.deal import DealCreate, DealOut, DealUpdate

from uuid import UUID 

router = APIRouter(prefix="", tags=["deals"])


def _get_owned_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _get_owned_deal(db: Session, deal_id: UUID, user: User) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None or deal.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.post("/customers/{customer_id}/deals", response_model=DealOut, status_code=201)
def create_deal(
    customer_id: UUID,
    payload: DealCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DealOut:
    customer = _get_owned_customer(db, customer_id, user)
    deal = Deal(
        customer_id=customer.id,
        owner_user_id=user.id,
        amount=payload.amount,
        status=payload.status,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.get("/customers/{customer_id}/deals", response_model=list[DealOut])
def list_deals(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DealOut]:
    _get_owned_customer(db, customer_id, user)
    return (
        db.query(Deal)
        .filter(Deal.customer_id == customer_id, Deal.owner_user_id == user.id)
        .order_by(Deal.id.asc())
        .all()
    )


@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DealOut:
    deal = _get_owned_deal(db, deal_id, user)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(deal, key, value)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal
