from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, User
from app.db.session import get_db
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate

from uuid import UUID 

router = APIRouter(prefix="/customers", tags=["customers"])


def _get_owned_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerOut:
    customer = Customer(
        owner_user_id=user.id,
        name=payload.name,
        email=str(payload.email) if payload.email is not None else None,
        phone=payload.phone,
        company=payload.company,
        next_follow_up_at=payload.next_follow_up_at,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("", response_model=list[CustomerOut])
def list_customers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CustomerOut]:
    return (
        db.query(Customer)
        .filter(Customer.owner_user_id == user.id)
        .order_by(Customer.id.asc())
        .all()
    )


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerOut:
    return _get_owned_customer(db, customer_id, user)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerOut:
    customer = _get_owned_customer(db, customer_id, user)

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "email" and value is not None:
            value = str(value)
        setattr(customer, key, value)
    customer.updated_at = datetime.utcnow()

    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer
