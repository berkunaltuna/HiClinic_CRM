from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import AuditLog, Customer, Deal, Interaction, OutboundMessage, Tag, CustomerTag, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.audit import AuditLogOut
from app.schemas.inbox import (
    InboxCustomerOut,
    ThreadItem,
    SetStageIn,
    SetFollowUpIn,
    TagActionIn,
    SendTextIn,
    SendTemplateIn,
    MarkConfirmedIn,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _bucket_for(customer: Customer, now: datetime, last_in: datetime | None, last_out: datetime | None) -> str:
    if (customer.stage or "").startswith("closed"):
        return "closed"
    if customer.next_follow_up_at is not None and customer.next_follow_up_at <= now:
        return "followup_due"
    if last_out is not None and (last_in is None or last_out >= last_in):
        return "waiting"
    return "open"


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and c.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


def _get_or_create_tag(db: Session, user: User, customer: Customer, name: str) -> Tag:
    clean = (name or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Tag is required")
    t = db.query(Tag).filter(Tag.owner_user_id == customer.owner_user_id, Tag.name == clean).first()
    if t:
        return t
    t = Tag(owner_user_id=customer.owner_user_id, name=clean)
    db.add(t)
    db.flush()
    return t


@router.get("/customers", response_model=list[InboxCustomerOut])
def list_inbox_customers(
    bucket: str | None = None,
    stage: str | None = None,
    event_id: UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InboxCustomerOut]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)

    last_in = (
        db.query(Interaction.customer_id.label("customer_id"), func.max(Interaction.occurred_at).label("last_in"))
        .filter(Interaction.direction == "inbound")
        .group_by(Interaction.customer_id)
        .subquery()
    )
    last_out = (
        db.query(Interaction.customer_id.label("customer_id"), func.max(Interaction.occurred_at).label("last_out"))
        .filter(Interaction.direction == "outbound")
        .group_by(Interaction.customer_id)
        .subquery()
    )

    cq = db.query(Customer)
    if not settings.share_customers_across_users:
        cq = cq.filter(Customer.owner_user_id == user.id)
    if stage:
        cq = cq.filter(Customer.stage == stage)
    if event_id:
        cq = cq.join(Deal, Deal.customer_id == Customer.id).filter(Deal.event_id == event_id)
    if q:
        like = f"%{q}%"
        cq = cq.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.email.ilike(like), Customer.company.ilike(like)))
    if tag:
        cq = cq.join(CustomerTag, CustomerTag.customer_id == Customer.id).join(Tag, Tag.id == CustomerTag.tag_id).filter(Tag.name == tag)

    customers = cq.order_by(Customer.updated_at.desc()).offset(offset).limit(limit).all()
    if not customers:
        return []

    ids = [c.id for c in customers]
    in_rows = dict(db.query(last_in.c.customer_id, last_in.c.last_in).filter(last_in.c.customer_id.in_(ids)).all())
    out_rows = dict(db.query(last_out.c.customer_id, last_out.c.last_out).filter(last_out.c.customer_id.in_(ids)).all())
    now = datetime.now(timezone.utc)

    out: list[InboxCustomerOut] = []
    for c in customers:
        li = in_rows.get(c.id)
        lo = out_rows.get(c.id)
        last_activity_at = None
        last_activity_direction = None
        if li and (not lo or li >= lo):
            last_activity_at = li
            last_activity_direction = "inbound"
        elif lo:
            last_activity_at = lo
            last_activity_direction = "outbound"

        b = _bucket_for(c, now, li, lo)
        if bucket and b != bucket:
            continue
        out.append(
            InboxCustomerOut(
                id=c.id,
                name=c.name,
                email=c.email,
                phone=c.phone,
                company=c.company,
                stage=c.stage,
                tags=c.tag_names,
                next_follow_up_at=c.next_follow_up_at,
                last_inbound_at=li,
                last_outbound_at=lo,
                last_activity_at=last_activity_at,
                last_activity_direction=last_activity_direction,
                bucket=b,
                latest_deal=c.latest_deal,
                lead_source=c.lead_source,
                form_id=c.form_id,
                form_name=c.form_name,
                campaign_id=c.campaign_id,
                campaign_name=c.campaign_name,
                adset_id=c.adset_id,
                adset_name=c.adset_name,
                ad_id=c.ad_id,
                ad_name=c.ad_name,
            )
        )

    def _sort_key(x: InboxCustomerOut):
        bucket_rank = {"followup_due": 0, "open": 1, "waiting": 2, "closed": 3}
        return (bucket_rank.get(x.bucket, 9), x.last_activity_at or datetime(1970, 1, 1, tzinfo=timezone.utc))

    out.sort(key=_sort_key, reverse=False)
    return out


@router.get("/customers/{customer_id}/thread", response_model=list[ThreadItem])
def get_thread(
    customer_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ThreadItem]:
    _get_customer(db, customer_id, user)

    interactions = db.query(Interaction).filter(Interaction.customer_id == customer_id).order_by(Interaction.occurred_at.desc()).limit(300).all()
    outbound = db.query(OutboundMessage).filter(OutboundMessage.customer_id == customer_id).order_by(OutboundMessage.created_at.desc()).limit(300).all()

    items: list[ThreadItem] = []
    for i in interactions:
        items.append(ThreadItem(kind="interaction", id=i.id, direction=i.direction, channel=i.channel, occurred_at=i.occurred_at, content=i.content, subject=i.subject, status=None, template_id=None))
    for m in outbound:
        items.append(ThreadItem(kind="outbound_message", id=m.id, direction="outbound", channel=m.channel, occurred_at=m.created_at, content=m.body, subject=None, status=m.status, template_id=m.template_id))

    items.sort(key=lambda x: x.occurred_at)
    return items


@router.get("/customers/{customer_id}/activity", response_model=list[AuditLogOut])
def get_customer_activity(
    customer_id: UUID,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditLogOut]:
    c = _get_customer(db, customer_id, user)
    deal_ids = [row[0] for row in db.query(Deal.id).filter(Deal.customer_id == c.id).all()]
    entity_filters = [
        (AuditLog.entity_type == "customer") & (AuditLog.entity_id == c.id),
    ]
    if deal_ids:
        entity_filters.append((AuditLog.entity_type == "deal") & (AuditLog.entity_id.in_(deal_ids)))
    # Some logs are attached to the customer through metadata rather than entity_id.
    entity_filters.append(AuditLog.meta.op("->>")("customer_id") == str(c.id))
    return (
        db.query(AuditLog)
        .filter(or_(*entity_filters))
        .order_by(AuditLog.created_at.desc())
        .limit(min(max(limit, 1), 500))
        .all()
    )


@router.post("/customers/{customer_id}/stage", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def set_stage(
    customer_id: UUID,
    payload: SetStageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = _get_customer(db, customer_id, user)
    before = {"stage": c.stage}
    c.stage = payload.stage
    c.updated_at = datetime.now(timezone.utc)
    latest_deal = c.latest_deal
    if latest_deal is not None:
        if payload.stage == "lost":
            latest_deal.status = "lost"
            latest_deal.lost_reason = payload.lost_reason or latest_deal.lost_reason
        elif payload.stage in ("deposit_paid", "treatment_completed", "treatment_done"):
            latest_deal.status = "won" if payload.stage in ("treatment_completed", "treatment_done") else latest_deal.status
    record_audit(
        db,
        actor=user,
        action="pipeline.stage_changed",
        entity_type="customer",
        entity_id=c.id,
        before=before,
        after={"stage": c.stage, "lost_reason": payload.lost_reason},
        metadata={"customer_id": str(c.id), "customer_name": c.name},
    )
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/followup", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def set_followup(
    customer_id: UUID,
    payload: SetFollowUpIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = _get_customer(db, customer_id, user)
    before = {"next_follow_up_at": c.next_follow_up_at.isoformat() if c.next_follow_up_at else None}
    if payload.minutes_from_now is not None:
        c.next_follow_up_at = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes_from_now)
    else:
        c.next_follow_up_at = payload.next_follow_up_at
    c.updated_at = datetime.now(timezone.utc)
    record_audit(
        db,
        actor=user,
        action="pipeline.followup_changed",
        entity_type="customer",
        entity_id=c.id,
        before=before,
        after={"next_follow_up_at": c.next_follow_up_at.isoformat() if c.next_follow_up_at else None},
        metadata={"customer_id": str(c.id), "customer_name": c.name},
    )
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/tags/add", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def add_tag(
    customer_id: UUID,
    payload: TagActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = _get_customer(db, customer_id, user)
    t = _get_or_create_tag(db, user, c, payload.tag)
    exists_link = db.query(CustomerTag).filter(CustomerTag.customer_id == customer_id, CustomerTag.tag_id == t.id).first()
    if not exists_link:
        db.add(CustomerTag(owner_user_id=c.owner_user_id, customer_id=customer_id, tag_id=t.id))
        record_audit(
            db,
            actor=user,
            action="pipeline.tag_added",
            entity_type="customer",
            entity_id=c.id,
            after={"tag": t.name},
            metadata={"customer_id": str(c.id), "customer_name": c.name},
        )
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/tags/remove", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def remove_tag(
    customer_id: UUID,
    payload: TagActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = _get_customer(db, customer_id, user)
    t = db.query(Tag).filter(Tag.owner_user_id == c.owner_user_id, Tag.name == payload.tag).first()
    if not t:
        return Response(status_code=204)
    deleted = db.query(CustomerTag).filter(CustomerTag.customer_id == customer_id, CustomerTag.tag_id == t.id).delete()
    if deleted:
        record_audit(
            db,
            actor=user,
            action="pipeline.tag_removed",
            entity_type="customer",
            entity_id=c.id,
            before={"tag": t.name},
            metadata={"customer_id": str(c.id), "customer_name": c.name},
        )
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/mark-confirmed", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def mark_confirmed(
    customer_id: UUID,
    payload: MarkConfirmedIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = _get_customer(db, customer_id, user)
    deal = c.latest_deal
    if deal is None:
        raise HTTPException(status_code=400, detail="Customer has no deal to confirm")
    before = {
        "confirmation_sent_at": deal.confirmation_sent_at.isoformat() if deal.confirmation_sent_at else None,
        "confirmation_channel": deal.confirmation_channel,
    }
    deal.confirmation_sent_at = datetime.now(timezone.utc)
    deal.confirmation_channel = payload.channel or "manual"
    deal.confirmed_by_user_id = user.id
    record_audit(
        db,
        actor=user,
        action="appointment.confirmation_marked",
        entity_type="deal",
        entity_id=deal.id,
        before=before,
        after={"confirmation_sent_at": deal.confirmation_sent_at.isoformat(), "confirmation_channel": deal.confirmation_channel},
        metadata={"customer_id": str(c.id), "customer_name": c.name},
    )
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/send-text", status_code=status.HTTP_201_CREATED)
def send_text(
    customer_id: UUID,
    payload: SendTextIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_customer(db, customer_id, user)

    not_before = None
    if payload.delay_minutes is not None and payload.delay_minutes > 0:
        not_before = datetime.now(timezone.utc) + timedelta(minutes=payload.delay_minutes)

    msg = OutboundMessage(
        owner_user_id=user.id,
        customer_id=customer_id,
        channel=payload.channel,
        status="queued",
        body=payload.body,
        not_before_at=not_before,
        cancel_on_inbound=payload.cancel_on_inbound,
    )
    db.add(msg)
    if payload.mark_confirmation:
        c = _get_customer(db, customer_id, user)
        deal = c.latest_deal
        if deal is not None:
            deal.confirmation_sent_at = datetime.now(timezone.utc)
            deal.confirmation_channel = payload.channel
            deal.confirmed_by_user_id = user.id
    record_audit(
        db,
        actor=user,
        action="pipeline.message_queued",
        entity_type="customer",
        entity_id=customer_id,
        after={"channel": msg.channel, "status": msg.status},
        metadata={"customer_id": str(customer_id)},
    )
    db.commit()
    db.refresh(msg)
    return {"id": str(msg.id), "status": msg.status}


@router.post("/customers/{customer_id}/send-template", status_code=status.HTTP_201_CREATED)
def send_template(
    customer_id: UUID,
    payload: SendTemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_customer(db, customer_id, user)

    not_before = None
    if payload.delay_minutes is not None and payload.delay_minutes > 0:
        not_before = datetime.now(timezone.utc) + timedelta(minutes=payload.delay_minutes)

    msg = OutboundMessage(
        owner_user_id=user.id,
        customer_id=customer_id,
        channel=payload.channel,
        status="queued",
        template_id=payload.template_id,
        variables=payload.variables,
        not_before_at=not_before,
        cancel_on_inbound=payload.cancel_on_inbound,
    )
    db.add(msg)
    if payload.mark_confirmation:
        c = _get_customer(db, customer_id, user)
        deal = c.latest_deal
        if deal is not None:
            deal.confirmation_sent_at = datetime.now(timezone.utc)
            deal.confirmation_channel = payload.channel
            deal.confirmation_template_id = payload.template_id
            deal.confirmed_by_user_id = user.id
    record_audit(
        db,
        actor=user,
        action="pipeline.template_queued",
        entity_type="customer",
        entity_id=customer_id,
        after={"channel": msg.channel, "status": msg.status, "template_id": str(msg.template_id) if msg.template_id else None},
        metadata={"customer_id": str(customer_id)},
    )
    db.commit()
    db.refresh(msg)
    return {"id": str(msg.id), "status": msg.status}
