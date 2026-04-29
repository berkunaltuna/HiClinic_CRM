from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.customer import CustomerOut

router = APIRouter(prefix="/followups", tags=["followups"])


@router.get("", response_model=list[CustomerOut])
def list_followups(
    date_: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CustomerOut]:
    now = datetime.now(tz=timezone.utc)

    q = db.query(Customer).filter(Customer.next_follow_up_at.isnot(None))
    if not settings.share_customers_across_users:
        q = q.filter(Customer.owner_user_id == user.id)

    if date_ is None:
        q = q.filter(Customer.next_follow_up_at <= now)
    else:
        start = datetime.combine(date_, time.min).replace(tzinfo=timezone.utc)
        end = datetime.combine(date_, time.max).replace(tzinfo=timezone.utc)
        q = q.filter(Customer.next_follow_up_at >= start, Customer.next_follow_up_at <= end)

    return q.order_by(Customer.next_follow_up_at.asc()).all()
