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
    """List customers due for follow-up on a given date (UTC).

    For Phase 1, we use UTC boundaries to keep the implementation simple.
    """
    target = date_ or datetime.now(tz=timezone.utc).date()
    start = datetime.combine(target, time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(target, time.max).replace(tzinfo=timezone.utc)

    return (
        db.query(Customer)
        .filter(
            Customer.owner_user_id == user.id,
            Customer.next_follow_up_at.isnot(None),
            Customer.next_follow_up_at >= start,
            Customer.next_follow_up_at <= end,
        )
        .order_by(Customer.next_follow_up_at.asc())
        .all()
    )
