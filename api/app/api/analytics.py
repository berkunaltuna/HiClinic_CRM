from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_, exists, text
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Interaction, OutboundMessage, OutcomeEvent, Template, User
from app.db.session import get_db
from app.schemas.outcome import KPIResponse, LeadsByDayPoint, TemplateEffectivenessRow


router = APIRouter(prefix="/analytics", tags=["analytics"])


def _dt(v: datetime | None, default: datetime) -> datetime:
    if v is None:
        return default
    # normalise naive datetimes to UTC
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


@router.get("/summary", response_model=KPIResponse)
def kpi_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KPIResponse:
    now = datetime.now(timezone.utc)
    end_dt = _dt(end, now)
    start_dt = _dt(start, end_dt - timedelta(days=30))

    leads_created = (
        db.query(func.count(Customer.id))
        .filter(Customer.owner_user_id == user.id)
        .filter(Customer.created_at >= start_dt)
        .filter(Customer.created_at < end_dt)
        .scalar()
        or 0
    )

    inbound_received = (
        db.query(func.count(Interaction.id))
        .filter(Interaction.owner_user_id == user.id)
        .filter(Interaction.direction == "inbound")
        .filter(Interaction.occurred_at >= start_dt)
        .filter(Interaction.occurred_at < end_dt)
        .scalar()
        or 0
    )

    outbound_sent = (
        db.query(func.count(OutboundMessage.id))
        .filter(OutboundMessage.owner_user_id == user.id)
        .filter(OutboundMessage.status == "sent")
        .filter(OutboundMessage.created_at >= start_dt)
        .filter(OutboundMessage.created_at < end_dt)
        .scalar()
        or 0
    )

    # Outcome counts
    outcome_rows = (
        db.query(OutcomeEvent.type, func.count(OutcomeEvent.id))
        .filter(OutcomeEvent.owner_user_id == user.id)
        .filter(OutcomeEvent.occurred_at >= start_dt)
        .filter(OutcomeEvent.occurred_at < end_dt)
        .group_by(OutcomeEvent.type)
        .all()
    )
    # SQLAlchemy returns OutcomeType enum instances; use .value to get stable API keys.
    outcomes = {getattr(t, "value", str(t)): int(c) for t, c in outcome_rows}

    # Conversion rates relative to new leads created in the window.
    denom = float(leads_created) if leads_created else 0.0
    conversion_rates: dict[str, float] = {}
    for k in ["consult_booked", "deposit_paid", "treatment_done", "lost"]:
        conversion_rates[k] = (outcomes.get(k, 0) / denom) if denom else 0.0

    # Median first response time (in seconds): first outbound after first inbound per customer in window.
    # Keep it simple + robust: compute in Python over a bounded set.
    inbound_first = (
        db.query(
            Interaction.customer_id.label("customer_id"),
            func.min(Interaction.occurred_at).label("first_inbound"),
        )
        .filter(Interaction.owner_user_id == user.id)
        .filter(Interaction.direction == "inbound")
        .filter(Interaction.occurred_at >= start_dt)
        .filter(Interaction.occurred_at < end_dt)
        .group_by(Interaction.customer_id)
        .subquery()
    )

    outbound_first_after = (
        db.query(
            OutboundMessage.customer_id.label("customer_id"),
            func.min(OutboundMessage.created_at).label("first_outbound"),
        )
        .join(inbound_first, inbound_first.c.customer_id == OutboundMessage.customer_id)
        .filter(OutboundMessage.owner_user_id == user.id)
        .filter(OutboundMessage.created_at >= inbound_first.c.first_inbound)
        .group_by(OutboundMessage.customer_id)
        .limit(5000)
        .all()
    )

    # Build a map for inbound times
    inbound_map = {
        r.customer_id: r.first_inbound
        for r in db.query(inbound_first.c.customer_id, inbound_first.c.first_inbound).all()
    }
    deltas: list[float] = []
    for row in outbound_first_after:
        fi = inbound_map.get(row.customer_id)
        fo = row.first_outbound
        if fi is not None and fo is not None:
            deltas.append((fo - fi).total_seconds())
    deltas.sort()
    median_first_response_seconds: float | None = None
    if deltas:
        mid = len(deltas) // 2
        median_first_response_seconds = deltas[mid] if len(deltas) % 2 == 1 else (deltas[mid - 1] + deltas[mid]) / 2

    return KPIResponse(
        start=start_dt,
        end=end_dt,
        leads_created=int(leads_created),
        outbound_sent=int(outbound_sent),
        inbound_received=int(inbound_received),
        median_first_response_seconds=median_first_response_seconds,
        outcomes=outcomes,
        conversion_rates=conversion_rates,
    )


@router.get("/leads-by-day", response_model=list[LeadsByDayPoint])
def leads_by_day(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LeadsByDayPoint]:
    now = datetime.now(timezone.utc)
    end_dt = _dt(end, now)
    start_dt = _dt(start, end_dt - timedelta(days=30))

    rows = (
        db.query(func.date(Customer.created_at).label("d"), func.count(Customer.id).label("c"))
        .filter(Customer.owner_user_id == user.id)
        .filter(Customer.created_at >= start_dt)
        .filter(Customer.created_at < end_dt)
        .group_by(func.date(Customer.created_at))
        .order_by(func.date(Customer.created_at))
        .all()
    )
    return [LeadsByDayPoint(date=str(r.d), leads=int(r.c)) for r in rows]


@router.get("/templates", response_model=list[TemplateEffectivenessRow])
def template_effectiveness(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateEffectivenessRow]:
    now = datetime.now(timezone.utc)
    end_dt = _dt(end, now)
    start_dt = _dt(start, end_dt - timedelta(days=30))

    # Sent template messages in range
    sent_q = (
        db.query(
            OutboundMessage.template_id.label("template_id"),
            func.count(OutboundMessage.id).label("sent"),
        )
        .filter(OutboundMessage.owner_user_id == user.id)
        .filter(OutboundMessage.status == "sent")
        .filter(OutboundMessage.template_id.isnot(None))
        .filter(OutboundMessage.created_at >= start_dt)
        .filter(OutboundMessage.created_at < end_dt)
        .group_by(OutboundMessage.template_id)
        .subquery()
    )

    # Replied within 7 days: any inbound interaction after message send and within +7d
    om = OutboundMessage
    inter = Interaction
    reply_exists = exists().where(
        and_(
            inter.owner_user_id == user.id,
            inter.customer_id == om.customer_id,
            inter.direction == "inbound",
            inter.occurred_at >= om.created_at,
            inter.occurred_at < (om.created_at + text("interval '7 days'")),
        )
    )

    replied_counts = (
        db.query(om.template_id.label("template_id"), func.count(om.id).label("replied"))
        .filter(om.owner_user_id == user.id)
        .filter(om.status == "sent")
        .filter(om.template_id.isnot(None))
        .filter(om.created_at >= start_dt)
        .filter(om.created_at < end_dt)
        .filter(reply_exists)
        .group_by(om.template_id)
        .subquery()
    )

    rows = (
        db.query(
            sent_q.c.template_id,
            Template.name,
            sent_q.c.sent,
            func.coalesce(replied_counts.c.replied, 0).label("replied"),
        )
        .join(Template, Template.id == sent_q.c.template_id)
        .outerjoin(replied_counts, replied_counts.c.template_id == sent_q.c.template_id)
        .order_by(sent_q.c.sent.desc())
        .all()
    )

    out: list[TemplateEffectivenessRow] = []
    for tid, name, sent, replied in rows:
        sent_i = int(sent or 0)
        replied_i = int(replied or 0)
        rate = (replied_i / sent_i) if sent_i else 0.0
        out.append(
            TemplateEffectivenessRow(
                template_id=tid,
                template_name=name,
                sent=sent_i,
                replied_within_7d=replied_i,
                reply_rate_7d=rate,
            )
        )
    return out
