from __future__ import annotations

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy.orm import Session, joinedload

from app.db.models import Appointment, Event, ImportBatch

EXPORT_HEADERS = [
    "Customer ID",
    "Booking ID",
    "Name",
    "Phone",
    "Email",
    "Treatment Interest",
    "Event",
    "Date",
    "Appointment Time",
    "Booking Status",
    "Notes",
]


def _appointment_row(appt: Appointment) -> list:
    customer = appt.customer
    deal = appt.deal
    starts = appt.starts_at
    return [
        str(appt.customer_id),
        str(appt.id),
        customer.name if customer else "",
        customer.phone if customer else "",
        customer.email if customer else "",
        deal.treatment_interest if deal else "",
        appt.event.name if appt.event else "",
        starts.strftime("%Y-%m-%d") if starts else "",
        starts.strftime("%H:%M") if starts else "",
        appt.status,
        appt.notes or "",
    ]


def build_export_workbook(
    db: Session, event: Event, *, day: date | None = None, status: str | None = None
) -> bytes:
    q = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.customer),
            joinedload(Appointment.deal),
            joinedload(Appointment.event),
        )
        .filter(Appointment.event_id == event.id)
    )
    if status:
        q = q.filter(Appointment.status == status)
    appts = q.order_by(Appointment.starts_at.asc()).all()
    if day is not None:
        appts = [a for a in appts if a.starts_at and a.starts_at.date() == day]

    wb = Workbook()
    ws = wb.active
    ws.title = "Bookings"
    ws.append(EXPORT_HEADERS)
    for appt in appts:
        ws.append(_appointment_row(appt))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_error_report(batch: ImportBatch) -> bytes:
    rows = [r for r in batch.rows if r.status in ("flagged", "error")]
    headers: list[str] = list(batch.rows[0].raw_data.keys()) if batch.rows else []

    wb = Workbook()
    ws = wb.active
    ws.title = "Import errors"
    ws.append([*headers, "Status", "Reasons"])
    for r in rows:
        values = [r.raw_data.get(h) for h in headers]
        ws.append([*values, r.status, "; ".join(r.reasons or [])])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
