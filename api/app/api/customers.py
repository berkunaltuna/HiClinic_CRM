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
from app.schemas.merge import MergeAnalysisOut, MergeCommitIn, MergeCommitOut, MergePreviewIn
from app.services.audit import record_audit
from app.services.customer_merge import MergeBlockedError, analyse_merge, lock_affected_events, lock_customers_ordered, merge_customers

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


@router.post("/{survivor_id}/merge/preview", response_model=MergeAnalysisOut)
def preview_customer_merge(
    survivor_id: UUID,
    payload: MergePreviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MergeAnalysisOut:
    if survivor_id == payload.loser_customer_id:
        raise HTTPException(status_code=400, detail="Cannot merge a customer with itself")
    survivor = _get_customer(db, survivor_id, user)
    loser = _get_customer(db, payload.loser_customer_id, user)
    analysis = analyse_merge(db, survivor=survivor, loser=loser)
    return MergeAnalysisOut(**analysis.as_dict())


@router.post("/{survivor_id}/merge/commit", response_model=MergeCommitOut)
def commit_customer_merge(
    survivor_id: UUID,
    payload: MergeCommitIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MergeCommitOut:
    if survivor_id == payload.loser_customer_id:
        raise HTTPException(status_code=400, detail="Cannot merge a customer with itself")
    _get_customer(db, survivor_id, user)
    _get_customer(db, payload.loser_customer_id, user)

    # Lock both customers (fixed order, avoids deadlock against a concurrent reverse merge),
    # then re-fetch and re-check visibility, then lock every event either of them has a booking
    # in before touching any Appointment row.
    lock_customers_ordered(db, survivor_id, payload.loser_customer_id)
    survivor = _get_customer(db, survivor_id, user)
    loser = _get_customer(db, payload.loser_customer_id, user)
    lock_affected_events(db, survivor.id, loser.id)

    # Recompute fresh under the locks -- never trust a client-held preview -- and compare against
    # what the client confirmed. A mismatch means something changed since preview; commit nothing
    # and hand back the updated analysis for re-confirmation instead.
    fresh_analysis = analyse_merge(db, survivor=survivor, loser=loser)
    if fresh_analysis.fingerprint != payload.confirmed_fingerprint:
        raise HTTPException(
            status_code=409,
            detail={"requires_reconfirmation": True, "analysis": fresh_analysis.as_dict()},
        )

    try:
        result = merge_customers(db, survivor=survivor, loser=loser, actor=user, analysis=fresh_analysis)
    except MergeBlockedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"requires_manual_resolution": True, "analysis": exc.analysis.as_dict()},
        ) from exc
    db.commit()
    db.refresh(survivor)
    return MergeCommitOut(
        survivor=survivor,
        filled_fields=result.filled_fields,
        cancelled_duplicate_appointment_ids=result.cancelled_duplicate_appointment_ids,
        analysis=MergeAnalysisOut(**result.analysis.as_dict()),
    )
