from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, User
from app.db.session import get_db
from app.schemas.customer import CustomerOut

router = APIRouter(prefix="/followups", tags=["followups"])


@router.get("", response_model=list[CustomerOut])
def list_followups(
    date_: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CustomerOut]:
    """
    If `date` is provided: return followups scheduled on that UTC date (within day bounds).
    If `date` is not provided: return followups that are due or overdue (<= now, UTC).
    """
    now = datetime.now(tz=timezone.utc)

    q = (
        db.query(Customer)
        .filter(
            Customer.owner_user_id == user.id,
            Customer.next_follow_up_at.isnot(None),
        )
    )

    if date_ is None:
        # due + overdue
        q = q.filter(Customer.next_follow_up_at <= now)
    else:
        # scheduled on that day (UTC)
        start = datetime.combine(date_, time.min).replace(tzinfo=timezone.utc)
        end = datetime.combine(date_, time.max).replace(tzinfo=timezone.utc)
        q = q.filter(Customer.next_follow_up_at >= start, Customer.next_follow_up_at <= end)

    return q.order_by(Customer.next_follow_up_at.asc()).all()
