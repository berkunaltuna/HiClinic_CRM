from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Appointment, Event, EventDay


def _minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def same_slot(existing: Appointment, starts: datetime, ends: datetime) -> bool:
    return (
        existing.starts_at.date() == starts.date()
        and existing.ends_at.date() == ends.date()
        and existing.starts_at.hour == starts.hour
        and existing.starts_at.minute == starts.minute
        and existing.ends_at.hour == ends.hour
        and existing.ends_at.minute == ends.minute
    )


def event_day_for_start(event: Event, starts: datetime) -> EventDay | None:
    start_date = starts.date()
    for day in event.days or []:
        if day.day == start_date:
            return day
    return None


@dataclass
class SlotCheck:
    ok: bool
    error: str | None = None
    http_status: int | None = None
    day: EventDay | None = None
    capacity: int | None = None
    booked_count: int | None = None


def validate_appointment_slot(
    event: Event,
    starts: datetime,
    ends: datetime,
    db: Session,
    exclude_appointment_id: UUID | None = None,
    *,
    ignore_capacity: bool = False,
) -> SlotCheck:
    """Pure (non-raising) extraction of the slot/capacity rules that used to live inline in
    events.py's _check_appointment. Returns a result instead of raising so both the manual
    booking endpoints (which raise HTTPException from it) and the bulk importer (which flags
    rows from it) share one implementation.

    ignore_capacity skips only the overlap/capacity sub-check (date/grid/break validation
    always still runs) -- used when the booking's resulting status is "cancelled", which never
    occupies capacity anywhere else in this app.
    """
    if ends <= starts:
        return SlotCheck(False, "Appointment end must be after start", 400)

    day = event_day_for_start(event, starts)
    if day is None:
        return SlotCheck(False, "Appointment must be on one of the event days", 400)

    expected_end = starts + timedelta(minutes=day.slot_minutes)
    if ends.replace(second=0, microsecond=0) != expected_end.replace(second=0, microsecond=0):
        return SlotCheck(False, f"Appointment must be exactly {day.slot_minutes} minutes", 400, day=day)

    starts_time = starts.time().replace(second=0, microsecond=0)
    start_minutes = _minutes_since_midnight(starts_time)
    day_start = _minutes_since_midnight(day.start_time)
    day_end = _minutes_since_midnight(day.end_time)
    if start_minutes < day_start or start_minutes + day.slot_minutes > day_end:
        return SlotCheck(False, "Appointment must be inside the event day hours", 400, day=day)
    if (start_minutes - day_start) % day.slot_minutes != 0:
        return SlotCheck(False, "Appointment start must match an available timetable slot", 400, day=day)
    if day.break_start_time and day.break_end_time:
        break_start = _minutes_since_midnight(day.break_start_time)
        break_end = _minutes_since_midnight(day.break_end_time)
        if start_minutes < break_end and start_minutes + day.slot_minutes > break_start:
            return SlotCheck(False, "Appointment overlaps the event break time", 400, day=day)

    if ignore_capacity:
        return SlotCheck(True, day=day)

    q = db.query(Appointment).filter(
        Appointment.event_id == event.id,
        Appointment.status != "cancelled",
        Appointment.starts_at < ends,
        Appointment.ends_at > starts,
    )
    if exclude_appointment_id:
        q = q.filter(Appointment.id != exclude_appointment_id)
    overlapping = q.all()
    misaligned = [a for a in overlapping if not same_slot(a, starts, ends)]
    if misaligned:
        return SlotCheck(
            False, "This slot overlaps an existing appointment that is not aligned to the timetable", 409, day=day
        )
    capacity = event.slot_capacity or 1
    if len(overlapping) >= capacity:
        return SlotCheck(
            False,
            f"This time slot is full ({capacity}/{capacity})",
            409,
            day=day,
            capacity=capacity,
            booked_count=len(overlapping),
        )
    return SlotCheck(True, day=day, capacity=capacity, booked_count=len(overlapping))


def lock_event_for_booking(db: Session, event_id: UUID) -> None:
    """Transaction-scoped Postgres advisory lock serializing booking writes for one event.

    Appointment has no DB-level slot-uniqueness constraint, so concurrent requests (two manual
    bookings, or a manual booking racing a bulk-import commit that holds its transaction open
    far longer) can both pass the capacity check under READ COMMITTED and overbook a slot. This
    closes that window without a new table or row lock surrogate. Released automatically at
    transaction end.
    """
    db.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:eid))"), {"eid": str(event_id)})
