from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.models import Appointment, Customer, Deal, Event, EventDay, User
from app.db.session import get_db
from app.schemas.event import AppointmentCreate, AppointmentOut, AppointmentUpdate, EventCreate, EventDayIn, EventDayOut, EventDayUpdate, EventOut, EventUpdate
from app.services.appointment_rules import event_day_for_start, lock_event_for_booking, validate_appointment_slot
from app.services.audit import record_audit

router = APIRouter(prefix="/events", tags=["events"])


def _event_snapshot(event: Event) -> dict:
    return {"name": event.name, "location": event.location, "starts_on": str(event.starts_on), "ends_on": str(event.ends_on), "default_slot_minutes": event.default_slot_minutes, "slot_capacity": event.slot_capacity, "is_active": event.is_active}


def _appointment_snapshot(appt: Appointment) -> dict:
    return {"customer_id": str(appt.customer_id), "deal_id": str(appt.deal_id) if appt.deal_id else None, "starts_at": appt.starts_at.isoformat() if appt.starts_at else None, "ends_at": appt.ends_at.isoformat() if appt.ends_at else None, "status": appt.status, "appointment_type": appt.appointment_type}


def _get_event(db: Session, event_id: UUID) -> Event:
    event = db.query(Event).options(joinedload(Event.days)).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _day_snapshot(day: EventDay) -> dict:
    def fmt(t):
        return t.strftime("%H:%M") if t else None

    return {"day": str(day.day), "start_time": fmt(day.start_time), "end_time": fmt(day.end_time), "slot_minutes": day.slot_minutes, "break_start_time": fmt(day.break_start_time), "break_end_time": fmt(day.break_end_time), "label": day.label}


def _validate_day_hours(day: EventDay) -> str | None:
    if day.end_time <= day.start_time:
        return "Day end time must be after start time"
    has_start, has_end = day.break_start_time is not None, day.break_end_time is not None
    if has_start != has_end:
        return "Break needs both a start and an end time"
    if has_start:
        if day.break_end_time <= day.break_start_time:
            return "Break end time must be after break start time"
        if day.break_start_time < day.start_time or day.break_end_time > day.end_time:
            return "Break must be inside the day hours"
    return None


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _validate_capacity_reduction(event: Event, new_capacity: int, db: Session) -> None:
    if new_capacity >= (event.slot_capacity or 1):
        return
    row = (
        db.query(Appointment.starts_at, func.count(Appointment.id).label("count"))
        .filter(Appointment.event_id == event.id, Appointment.status != "cancelled")
        .group_by(Appointment.starts_at)
        .having(func.count(Appointment.id) > new_capacity)
        .order_by(func.count(Appointment.id).desc())
        .first()
    )
    if row:
        when = row.starts_at.strftime("%Y-%m-%d %H:%M") if row.starts_at else "an existing slot"
        raise HTTPException(status_code=400, detail=f"Cannot reduce capacity to {new_capacity}; {when} already has {row.count} appointments")


def _check_appointment(
    event: Event,
    payload: AppointmentCreate | AppointmentUpdate,
    db: Session,
    appointment_id: UUID | None = None,
    *,
    ignore_capacity: bool = False,
) -> None:
    starts = payload.starts_at
    ends = payload.ends_at
    if starts is None or ends is None:
        return
    result = validate_appointment_slot(
        event, starts, ends, db, exclude_appointment_id=appointment_id, ignore_capacity=ignore_capacity
    )
    if not result.ok:
        raise HTTPException(status_code=result.http_status or 400, detail=result.error)


@router.get("", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[EventOut]:
    return db.query(Event).options(joinedload(Event.days)).order_by(Event.starts_on.desc(), Event.created_at.desc()).all()


@router.post("", response_model=EventOut, status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> EventOut:
    event = Event(owner_user_id=user.id, name=payload.name, location=payload.location, description=payload.description, starts_on=payload.starts_on, ends_on=payload.ends_on, default_slot_minutes=payload.default_slot_minutes, slot_capacity=payload.slot_capacity, is_active=payload.is_active)
    db.add(event)
    db.flush()
    days = payload.days or [EventDayIn(day=payload.starts_on, slot_minutes=payload.default_slot_minutes)]
    for d in days:
        db.add(EventDay(event_id=event.id, day=d.day, start_time=d.start_time, end_time=d.end_time, slot_minutes=d.slot_minutes, break_start_time=d.break_start_time, break_end_time=d.break_end_time, label=d.label))
    record_audit(db, actor=user, action="event.created", entity_type="event", entity_id=event.id, after={"name": event.name})
    db.commit()
    db.refresh(event)
    return _get_event(db, event.id)


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> EventOut:
    return _get_event(db, event_id)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: UUID, payload: EventUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> EventOut:
    event = _get_event(db, event_id)
    before = _event_snapshot(event)
    data = payload.model_dump(exclude_unset=True)
    if "slot_capacity" in data and data["slot_capacity"] is not None:
        _validate_capacity_reduction(event, data["slot_capacity"], db)
    for k, v in data.items():
        setattr(event, k, v)
    event.updated_at = datetime.now(timezone.utc)
    db.add(event)
    record_audit(db, actor=user, action="event.updated", entity_type="event", entity_id=event.id, before=before, after=_event_snapshot(event))
    db.commit()
    return _get_event(db, event_id)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_event(event_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    event = _get_event(db, event_id)
    before = _event_snapshot(event)
    db.delete(event)
    record_audit(db, actor=user, action="event.deleted", entity_type="event", entity_id=event_id, before=before)
    db.commit()
    return Response(status_code=204)


@router.post("/{event_id}/days", response_model=EventDayOut, status_code=201)
def add_event_day(event_id: UUID, payload: EventDayIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> EventDayOut:
    _get_event(db, event_id)
    day = EventDay(event_id=event_id, day=payload.day, start_time=payload.start_time, end_time=payload.end_time, slot_minutes=payload.slot_minutes, break_start_time=payload.break_start_time, break_end_time=payload.break_end_time, label=payload.label)
    db.add(day)
    record_audit(db, actor=user, action="event_day.created", entity_type="event", entity_id=event_id, after={"day": str(payload.day)})
    db.commit()
    db.refresh(day)
    return day


@router.patch("/{event_id}/days/{day_id}", response_model=EventDayOut)
def update_event_day(event_id: UUID, day_id: UUID, payload: EventDayUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> EventDayOut:
    lock_event_for_booking(db, event_id)
    event = _get_event(db, event_id)
    day = next((d for d in event.days if d.id == day_id), None)
    if day is None:
        raise HTTPException(status_code=404, detail="Event day not found")
    before = _day_snapshot(day)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k in ("start_time", "end_time", "slot_minutes") and v is None:
            continue
        setattr(day, k, v)

    error = _validate_day_hours(day)
    if error is None:
        # Every active booking on this day must still land on a valid slot under the new hours,
        # otherwise it would silently drop out of the timetable.
        active = (
            db.query(Appointment)
            .options(joinedload(Appointment.customer))
            .filter(Appointment.event_id == event_id, Appointment.status != "cancelled")
            .order_by(Appointment.starts_at.asc())
            .all()
        )
        for appt in active:
            if event_day_for_start(event, appt.starts_at) is not day:
                continue
            check = validate_appointment_slot(event, appt.starts_at, appt.ends_at, db, ignore_capacity=True)
            if not check.ok:
                who = appt.customer_name or "a customer"
                error = f"{who}'s booking at {appt.starts_at.strftime('%H:%M')} would no longer fit these hours ({check.error}). Move or cancel it first."
                break
    if error:
        db.rollback()
        raise HTTPException(status_code=400, detail=error)

    event.updated_at = datetime.now(timezone.utc)
    record_audit(db, actor=user, action="event_day.updated", entity_type="event", entity_id=event_id, before=before, after=_day_snapshot(day))
    db.commit()
    db.refresh(day)
    return day


@router.get("/{event_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(event_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[AppointmentOut]:
    _get_event(db, event_id)
    return db.query(Appointment).options(joinedload(Appointment.customer), joinedload(Appointment.deal)).filter(Appointment.event_id == event_id).order_by(Appointment.starts_at.asc()).all()


@router.post("/{event_id}/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(event_id: UUID, payload: AppointmentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AppointmentOut:
    event = _get_event(db, event_id)
    customer = _get_customer(db, payload.customer_id, user)
    if payload.deal_id and db.get(Deal, payload.deal_id) is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    lock_event_for_booking(db, event.id)
    _check_appointment(event, payload, db)
    deal = db.get(Deal, payload.deal_id) if payload.deal_id else customer.latest_deal
    if deal is None:
        # Every booked customer needs a deal so the pipeline's event filter
        # (which matches on Deal.event_id) and the "Event assigned" badge pick them up.
        deal = Deal(customer_id=customer.id, owner_user_id=user.id, amount=0, status="open")
        db.add(deal)
        db.flush()
        record_audit(db, actor=user, action="deal.created", entity_type="deal", entity_id=deal.id, after={"customer_id": str(customer.id), "status": deal.status, "amount": 0.0})
    deal.event_id = event.id
    appt = Appointment(event_id=event.id, customer_id=customer.id, deal_id=deal.id, assigned_user_id=payload.assigned_user_id or user.id, starts_at=payload.starts_at, ends_at=payload.ends_at, appointment_type=payload.appointment_type, status=payload.status, notes=payload.notes)
    customer.stage = "appointment_booked"
    db.add(appt)
    record_audit(db, actor=user, action="appointment.created", entity_type="appointment", entity_id=appt.id, after={"customer_id": str(customer.id), "event_id": str(event.id), "starts_at": payload.starts_at.isoformat()})
    db.commit()
    db.refresh(appt)
    return appt


@router.patch("/{event_id}/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(event_id: UUID, appointment_id: UUID, payload: AppointmentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AppointmentOut:
    _get_event(db, event_id)
    appt = db.get(Appointment, appointment_id)
    if appt is None or appt.event_id != event_id:
        raise HTTPException(status_code=404, detail="Appointment not found")
    lock_event_for_booking(db, event_id)
    before = _appointment_snapshot(appt)
    data = payload.model_dump(exclude_unset=True)
    starts = data.get("starts_at", appt.starts_at)
    ends = data.get("ends_at", appt.ends_at)
    check_payload = AppointmentUpdate(starts_at=starts, ends_at=ends)
    _check_appointment(appt.event, check_payload, db, appointment_id=appt.id)
    for k, v in data.items():
        setattr(appt, k, v)
    appt.updated_at = datetime.now(timezone.utc)
    db.add(appt)
    record_audit(db, actor=user, action="appointment.updated", entity_type="appointment", entity_id=appt.id, before=before, after=_appointment_snapshot(appt))
    db.commit()
    db.refresh(appt)
    return appt


@router.delete("/{event_id}/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_appointment(event_id: UUID, appointment_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    appt = db.get(Appointment, appointment_id)
    if appt is None or appt.event_id != event_id:
        raise HTTPException(status_code=404, detail="Appointment not found")
    before = _appointment_snapshot(appt)
    db.delete(appt)
    record_audit(db, actor=user, action="appointment.deleted", entity_type="appointment", entity_id=appointment_id, before=before)
    db.commit()
    return Response(status_code=204)
