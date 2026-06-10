from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, CustomerTag, Deal, OutboundMessage, FacebookLeadEvent, OutboundMessage, OutcomeEvent, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/customers", tags=["customers"])


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and customer.owner_user_id != user.id:
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
        can_contact=payload.can_contact,
        language=payload.language,
        lead_source=payload.lead_source,
        form_id=payload.form_id,
        form_name=payload.form_name,
        campaign_id=payload.campaign_id,
        campaign_name=payload.campaign_name,
        adset_id=payload.adset_id,
        adset_name=payload.adset_name,
        ad_id=payload.ad_id,
        ad_name=payload.ad_name,
    )
    db.add(customer)
    db.flush()
    record_audit(db, actor=user, action="customer.created", entity_type="customer", entity_id=customer.id, after={"name": customer.name, "email": customer.email, "phone": customer.phone})
    db.commit()
    db.refresh(customer)
    return customer


@router.get("", response_model=list[CustomerOut])
def list_customers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CustomerOut]:
    q = db.query(Customer)
    if not settings.share_customers_across_users:
        q = q.filter(Customer.owner_user_id == user.id)
    return q.order_by(Customer.updated_at.desc(), Customer.id.asc()).all()


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerOut:
    return _get_customer(db, customer_id, user)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CustomerOut:
    customer = _get_customer(db, customer_id, user)

    before = {"name": customer.name, "email": customer.email, "phone": customer.phone, "stage": customer.stage, "lead_source": customer.lead_source, "form_name": customer.form_name, "campaign_name": customer.campaign_name, "adset_name": customer.adset_name, "ad_name": customer.ad_name}
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "email" and value is not None:
            value = str(value)
        setattr(customer, key, value)
    customer.updated_at = datetime.now(tz=timezone.utc)

    db.add(customer)
    record_audit(db, actor=user, action="customer.updated", entity_type="customer", entity_id=customer.id, before=before, after={"name": customer.name, "email": customer.email, "phone": customer.phone, "stage": customer.stage, "lead_source": customer.lead_source, "form_name": customer.form_name, "campaign_name": customer.campaign_name, "adset_name": customer.adset_name, "ad_name": customer.ad_name})
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    customer = _get_customer(db, customer_id, user)

    db.query(FacebookLeadEvent).filter(FacebookLeadEvent.customer_id == customer.id).update(
        {FacebookLeadEvent.customer_id: None},
        synchronize_session=False,
    )

    deal_ids = [row[0] for row in db.query(Deal.id).filter(Deal.customer_id == customer.id).all()]
    if deal_ids:
        db.query(FacebookLeadEvent).filter(FacebookLeadEvent.deal_id.in_(deal_ids)).update(
            {FacebookLeadEvent.deal_id: None},
            synchronize_session=False,
        )

    db.query(CustomerTag).filter(CustomerTag.customer_id == customer.id).delete(synchronize_session=False)
    db.query(OutboundMessage).filter(OutboundMessage.customer_id == customer.id).delete(synchronize_session=False)
    db.query(OutcomeEvent).filter(OutcomeEvent.customer_id == customer.id).delete(synchronize_session=False)

    before = {"name": customer.name, "email": customer.email, "phone": customer.phone}
    db.delete(customer)
    record_audit(db, actor=user, action="customer.deleted", entity_type="customer", entity_id=customer_id, before=before)
    db.commit()
    return Response(status_code=204)
