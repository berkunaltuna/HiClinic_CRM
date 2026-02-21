from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Interaction, OutboundMessage, Tag, CustomerTag, User
from app.db.session import get_db
from app.schemas.inbox import (
    InboxCustomerOut,
    ThreadItem,
    SetStageIn,
    SetFollowUpIn,
    TagActionIn,
    SendTextIn,
    SendTemplateIn,
)


router = APIRouter(prefix="/inbox", tags=["inbox"])


def _bucket_for(customer: Customer, now: datetime, last_in: datetime | None, last_out: datetime | None) -> str:
    if (customer.stage or "").startswith("closed"):
        return "closed"
    if customer.next_follow_up_at is not None and customer.next_follow_up_at <= now:
        return "followup_due"
    if last_out is not None and (last_in is None or last_out >= last_in):
        return "waiting"
    return "open"


@router.get("/customers", response_model=list[InboxCustomerOut])
def list_inbox_customers(
    bucket: str | None = None,
    stage: str | None = None,
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
        .filter(Interaction.owner_user_id == user.id)
        .filter(Interaction.direction == "inbound")
        .group_by(Interaction.customer_id)
        .subquery()
    )
    last_out = (
        db.query(Interaction.customer_id.label("customer_id"), func.max(Interaction.occurred_at).label("last_out"))
        .filter(Interaction.owner_user_id == user.id)
        .filter(Interaction.direction == "outbound")
        .group_by(Interaction.customer_id)
        .subquery()
    )

    cq = db.query(Customer).filter(Customer.owner_user_id == user.id)
    if stage:
        cq = cq.filter(Customer.stage == stage)
    if q:
        like = f"%{q}%"
        cq = cq.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.email.ilike(like), Customer.company.ilike(like)))
    if tag:
        cq = (
            cq.join(CustomerTag, CustomerTag.customer_id == Customer.id)
            .join(Tag, Tag.id == CustomerTag.tag_id)
            .filter(Tag.owner_user_id == user.id)
            .filter(Tag.name == tag)
        )

    # fetch base customers
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
            )
        )

    # Sort: followup_due first, then most recent activity
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
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    interactions = (
        db.query(Interaction)
        .filter(Interaction.owner_user_id == user.id)
        .filter(Interaction.customer_id == customer_id)
        .order_by(Interaction.occurred_at.desc())
        .limit(300)
        .all()
    )
    outbound = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.owner_user_id == user.id)
        .filter(OutboundMessage.customer_id == customer_id)
        .order_by(OutboundMessage.created_at.desc())
        .limit(300)
        .all()
    )

    items: list[ThreadItem] = []
    for i in interactions:
        items.append(
            ThreadItem(
                kind="interaction",
                id=i.id,
                direction=i.direction,
                channel=i.channel,
                occurred_at=i.occurred_at,
                content=i.content,
                subject=i.subject,
                status=None,
                template_id=None,
            )
        )
    for m in outbound:
        items.append(
            ThreadItem(
                kind="outbound_message",
                id=m.id,
                direction="outbound",
                channel=m.channel,
                occurred_at=m.created_at,
                content=m.body,
                subject=None,
                status=m.status,
                template_id=m.template_id,
            )
        )

    items.sort(key=lambda x: x.occurred_at)
    return items


@router.post("/customers/{customer_id}/stage", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def set_stage(
    customer_id: UUID,
    payload: SetStageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    c.stage = payload.stage
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/followup", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def set_followup(
    customer_id: UUID,
    payload: SetFollowUpIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if payload.minutes_from_now is not None:
        c.next_follow_up_at = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes_from_now)
    else:
        c.next_follow_up_at = payload.next_follow_up_at
    db.commit()
    return Response(status_code=204)


def _get_or_create_tag(db: Session, user: User, name: str) -> Tag:
    t = db.query(Tag).filter(Tag.owner_user_id == user.id, Tag.name == name).first()
    if t:
        return t
    t = Tag(owner_user_id=user.id, name=name)
    db.add(t)
    db.flush()
    return t


@router.post("/customers/{customer_id}/tags/add", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def add_tag(
    customer_id: UUID,
    payload: TagActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    t = _get_or_create_tag(db, user, payload.tag)
    exists_link = (
        db.query(CustomerTag)
        .filter(CustomerTag.customer_id == customer_id, CustomerTag.tag_id == t.id)
        .first()
    )
    if not exists_link:
        db.add(CustomerTag(owner_user_id=user.id, customer_id=customer_id, tag_id=t.id))
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/tags/remove", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def remove_tag(
    customer_id: UUID,
    payload: TagActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    t = db.query(Tag).filter(Tag.owner_user_id == user.id, Tag.name == payload.tag).first()
    if not t:
        return Response(status_code=204)
    db.query(CustomerTag).filter(CustomerTag.customer_id == customer_id, CustomerTag.tag_id == t.id).delete()
    db.commit()
    return Response(status_code=204)


@router.post("/customers/{customer_id}/send-text", status_code=status.HTTP_201_CREATED)
def send_text(
    customer_id: UUID,
    payload: SendTextIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

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
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

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
    db.commit()
    db.refresh(msg)
    return {"id": str(msg.id), "status": msg.status}
