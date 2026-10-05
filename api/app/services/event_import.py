from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

import openpyxl
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Appointment, Customer, Deal, Event, ImportBatch, ImportRow, User
from app.services.appointment_rules import event_day_for_start, lock_event_for_booking, validate_appointment_slot
from app.services.audit import record_audit
from app.services.matching import find_customer_candidates, normalise_email, normalise_phone

STUCK_COMMIT_THRESHOLD = timedelta(minutes=10)

TARGET_FIELDS = [
    "customer_id",
    "booking_id",
    "name",
    "phone",
    "email",
    "treatment_interest",
    "event",
    "date",
    "appointment_time",
    "booking_status",
    "notes",
]

FIELD_SYNONYMS: dict[str, list[str]] = {
    "customer_id": ["customer", "crm id", "crm customer id", "id"],
    "booking_id": ["appointment id", "booking"],
    "name": ["full name", "customer name", "patient name"],
    "phone": ["phone number", "mobile", "telephone", "contact number"],
    "email": ["email address"],
    "treatment_interest": ["treatment", "procedure"],
    "event": ["event name"],
    "date": ["appointment date", "booking date"],
    "appointment_time": ["time", "slot"],
    "booking_status": ["status"],
    "notes": ["note", "comments"],
}

ALLOWED_BOOKING_STATUSES = {"booked", "cancelled"}


# ---------------------------------------------------------------------------
# Upload / parsing
# ---------------------------------------------------------------------------


def _stringify_cell(value) -> str | None:
    """Coerce any Excel/CSV cell value into a JSON-safe, unambiguous string for storage in
    ImportRow.raw_data. Dates/times use the exact format the exporter and parser both expect
    (YYYY-MM-DD / HH:MM) so a native Excel date/time cell never needs ambiguous re-parsing
    later. A blank cell is always None, never the string "None"/"nan"."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value).strip() or None


def parse_upload_file(filename: str, content: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    lower = (filename or "").lower()
    try:
        if lower.endswith(".csv"):
            return _parse_csv(content)
        if lower.endswith(".xlsx"):
            return _parse_xlsx(content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}") from exc
    raise HTTPException(status_code=400, detail="Unsupported file type; expected .xlsx or .csv")


def _parse_csv(content: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h for h in (reader.fieldnames or []) if h]
    rows: list[dict[str, str | None]] = []
    for raw_row in reader:
        rows.append({h: _stringify_cell(raw_row.get(h)) for h in headers})
    return headers, rows


def _parse_xlsx(content: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []
    headers = [str(h).strip() if h is not None else f"Column{i + 1}" for i, h in enumerate(header_row)]
    rows: list[dict[str, str | None]] = []
    for raw in rows_iter:
        if raw is None or all(v is None for v in raw):
            continue
        row: dict[str, str | None] = {}
        for i, h in enumerate(headers):
            value = raw[i] if i < len(raw) else None
            row[h] = _stringify_cell(value)
        rows.append(row)
    return headers, rows


def _key(text: str) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    keyed = {_key(h): h for h in headers}
    mapping: dict[str, str] = {}
    for target, synonyms in FIELD_SYNONYMS.items():
        for candidate in [target, *synonyms]:
            k = _key(candidate)
            if k in keyed:
                mapping[target] = keyed[k]
                break
    return mapping


def create_batch_from_upload(
    db: Session, *, event: Event, user: User, filename: str, content: bytes
) -> ImportBatch:
    max_bytes = settings.import_max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds the {settings.import_max_file_size_mb}MB limit")

    headers, rows = parse_upload_file(filename, content)
    if len(rows) > settings.import_max_rows:
        raise HTTPException(status_code=400, detail=f"File has {len(rows)} rows; the limit is {settings.import_max_rows}")

    source_format = "csv" if filename.lower().endswith(".csv") else "xlsx"
    batch = ImportBatch(
        owner_user_id=user.id,
        event_id=event.id,
        event_name_snapshot=event.name,
        source_filename=filename,
        source_format=source_format,
        status="uploaded",
        row_count=len(rows),
    )
    db.add(batch)
    db.flush()
    for i, raw in enumerate(rows, start=1):
        db.add(ImportRow(batch_id=batch.id, row_number=i, raw_data=raw, status="pending"))
    db.commit()
    db.refresh(batch)
    return batch


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------


@dataclass
class ParsedFields:
    customer_id: UUID | None = None
    booking_id: UUID | None = None
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    treatment_interest: str | None = None
    event_name: str | None = None
    appt_date: date | None = None
    appt_time: time | None = None
    booking_status: str = "booked"
    notes: str | None = None
    parse_errors: list[str] = field(default_factory=list)


def _cell(raw_data: dict, mapping: dict[str, str], target: str) -> str | None:
    header = mapping.get(target)
    if not header:
        return None
    value = raw_data.get(header)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date_cell(value: str | None, errors: list[str]) -> date | None:
    if not value:
        return None
    date_part = value.strip().split(" ")[0]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"invalid Date '{value}', expected YYYY-MM-DD")
        return None


def _parse_time_cell(value: str | None, errors: list[str]) -> time | None:
    if not value:
        return None
    text = value.strip()
    time_part = text.split(" ")[-1]
    try:
        return datetime.strptime(time_part, "%H:%M").time()
    except ValueError:
        errors.append(f"invalid Appointment Time '{value}', expected HH:MM")
        return None


def parse_mapped_fields(raw_data: dict, mapping: dict[str, str]) -> ParsedFields:
    errors: list[str] = []

    customer_id = None
    raw_cid = _cell(raw_data, mapping, "customer_id")
    if raw_cid:
        try:
            customer_id = UUID(raw_cid)
        except ValueError:
            errors.append(f"invalid Customer ID '{raw_cid}'")

    booking_id = None
    raw_bid = _cell(raw_data, mapping, "booking_id")
    if raw_bid:
        try:
            booking_id = UUID(raw_bid)
        except ValueError:
            errors.append(f"invalid Booking ID '{raw_bid}'")

    name = _cell(raw_data, mapping, "name")
    phone = normalise_phone(_cell(raw_data, mapping, "phone"))
    email = normalise_email(_cell(raw_data, mapping, "email"))
    treatment_interest = _cell(raw_data, mapping, "treatment_interest")
    event_name = _cell(raw_data, mapping, "event")
    notes = _cell(raw_data, mapping, "notes")

    status_raw = _cell(raw_data, mapping, "booking_status")
    if status_raw is None:
        booking_status = "booked"
    else:
        low = status_raw.strip().lower()
        if low in ALLOWED_BOOKING_STATUSES:
            booking_status = low
        else:
            errors.append(f"invalid Booking Status '{status_raw}', expected 'booked' or 'cancelled'")
            booking_status = "booked"

    appt_date = _parse_date_cell(_cell(raw_data, mapping, "date"), errors)
    appt_time = _parse_time_cell(_cell(raw_data, mapping, "appointment_time"), errors)
    if appt_date is None and not any("Date" in e for e in errors):
        errors.append("missing Date")
    if appt_time is None and not any("Appointment Time" in e for e in errors):
        errors.append("missing Appointment Time")
    if not name:
        errors.append("missing Name")

    return ParsedFields(
        customer_id=customer_id,
        booking_id=booking_id,
        name=name,
        phone=phone,
        email=email,
        treatment_interest=treatment_interest,
        event_name=event_name,
        appt_date=appt_date,
        appt_time=appt_time,
        booking_status=booking_status,
        notes=notes,
        parse_errors=errors,
    )


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _as_naive(value: datetime | None) -> datetime | None:
    """Strip tzinfo if present.

    The app's convention (confirmed throughout events.py and the frontend) is to treat
    appointment times as naive clinic-local wall-clock values, never converting through a
    timezone. Appointment.starts_at/ends_at are stored as a naive datetime, but once an ORM
    object is expired and re-fetched (e.g. right after a nested-transaction/SAVEPOINT commit,
    which expires session objects same as an outer commit), psycopg3 deserialises the
    TIMESTAMPTZ column back as a timezone-aware (UTC) datetime. Comparing that directly against
    a freshly built naive datetime.combine(...) value would wrongly report a difference, so
    every Python-side equality check against a stored starts_at/ends_at normalises both sides
    through this helper first.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _customer_snapshot(c: Customer) -> dict:
    return {"name": c.name, "email": c.email, "phone": c.phone, "stage": c.stage}


def _appt_snapshot(a: Appointment) -> dict:
    return {
        "starts_at": _as_naive(a.starts_at).isoformat() if a.starts_at else None,
        "ends_at": _as_naive(a.ends_at).isoformat() if a.ends_at else None,
        "status": a.status,
        "notes": a.notes,
    }


# ---------------------------------------------------------------------------
# Simulation state and per-row outcome
# ---------------------------------------------------------------------------


@dataclass
class PreviewState:
    simulated_customer_rows: dict[UUID, int] = field(default_factory=dict)
    simulated_appointment_rows: dict[UUID, int] = field(default_factory=dict)


@dataclass
class CustomerRef:
    kind: str  # "existing" | "new"
    id: UUID
    batch_row_number: int | None = None
    display_name: str | None = None


@dataclass
class AppointmentRef:
    kind: str  # "existing" | "new"
    id: UUID
    batch_row_number: int | None = None


@dataclass
class RowOutcome:
    status: str  # "created" | "updated" | "unchanged" | "flagged" | "error"
    reasons: list[str] = field(default_factory=list)
    match_type: str | None = None  # "id" | "phone" | "email" | "batch" | "none"
    customer_ref: CustomerRef | None = None
    appointment_ref: AppointmentRef | None = None
    customer_changed: bool = False
    booking_created: bool = False
    booking_updated: bool = False


def _resolve_or_create_customer(
    db: Session, *, resolution, fields: ParsedFields, user: User, state: PreviewState, row_number: int
):
    if resolution.customer is not None:
        customer = resolution.customer
        before = _customer_snapshot(customer)
        changed = False
        if fields.name and _blank(customer.name):
            customer.name = fields.name
            changed = True
        if fields.phone and _blank(customer.phone):
            customer.phone = fields.phone
            changed = True
        if fields.email and _blank(customer.email):
            customer.email = fields.email
            changed = True
        audit_call = None
        if changed:
            db.add(customer)
            db.flush()
            audit_call = dict(
                actor=user,
                action="customer.import_updated",
                entity_type="customer",
                entity_id=customer.id,
                before=before,
                after=_customer_snapshot(customer),
            )
        provisional_row = state.simulated_customer_rows.get(customer.id)
        kind = "new" if provisional_row is not None else "existing"
        return customer, changed, audit_call, kind, provisional_row

    customer = Customer(
        owner_user_id=user.id,
        name=fields.name or fields.phone or fields.email or "Imported Lead",
        email=fields.email,
        phone=fields.phone,
    )
    db.add(customer)
    db.flush()
    state.simulated_customer_rows[customer.id] = row_number
    audit_call = dict(
        actor=user,
        action="customer.import_created",
        entity_type="customer",
        entity_id=customer.id,
        after=_customer_snapshot(customer),
    )
    return customer, True, audit_call, "new", row_number


@dataclass
class BookingOutcome:
    status: str  # "ok" | "flagged" | "error"
    reasons: list[str] = field(default_factory=list)
    appointment: Appointment | None = None
    created: bool = False
    appointment_changed: bool = False
    pending_audit_calls: list[dict] = field(default_factory=list)


def _resolve_deal_for_import(db: Session, customer: Customer, event: Event, user: User, audit_calls: list[dict]) -> Deal | None:
    deal = customer.latest_deal
    if deal is not None and deal.status == "open" and (deal.event_id is None or deal.event_id == event.id):
        deal.event_id = event.id
        db.add(deal)
        return deal
    deal = Deal(customer_id=customer.id, owner_user_id=user.id, amount=0, status="open", event_id=event.id)
    db.add(deal)
    db.flush()
    audit_calls.append(
        dict(
            actor=user,
            action="deal.created",
            entity_type="deal",
            entity_id=deal.id,
            after={"customer_id": str(customer.id), "status": deal.status, "amount": 0.0, "event_id": str(event.id)},
        )
    )
    return deal


def _resolve_booking(
    db: Session, *, event: Event, customer: Customer, fields: ParsedFields, user: User, state: PreviewState, row_number: int
) -> BookingOutcome:
    if fields.event_name and fields.event_name.strip().lower() != (event.name or "").strip().lower():
        return BookingOutcome("flagged", ["event name in the sheet does not match the selected event"])

    target_status = fields.booking_status
    starts = datetime.combine(fields.appt_date, fields.appt_time)

    existing: Appointment | None = None

    if fields.booking_id is not None:
        appt = db.get(Appointment, fields.booking_id)
        if appt is None or appt.event_id != event.id or appt.customer_id != customer.id:
            return BookingOutcome("flagged", ["booking ID does not match this event and customer"])
        existing = appt
    else:
        exact_matches = (
            db.query(Appointment)
            .filter(
                Appointment.event_id == event.id,
                Appointment.customer_id == customer.id,
                Appointment.starts_at == starts,
            )
            .all()
        )
        if len(exact_matches) > 1:
            return BookingOutcome("flagged", ["multiple existing bookings match this exact date/time"])
        if len(exact_matches) == 1:
            existing = exact_matches[0]
        else:
            active = (
                db.query(Appointment)
                .filter(
                    Appointment.event_id == event.id,
                    Appointment.customer_id == customer.id,
                    Appointment.status != "cancelled",
                )
                .all()
            )
            if len(active) > 1:
                return BookingOutcome("flagged", ["ambiguous -- multiple active bookings for this customer at this event"])
            if len(active) == 1:
                return BookingOutcome("flagged", ["existing active booking at a different time"])
            existing = None

    day = event_day_for_start(event, starts)
    if day is None:
        return BookingOutcome("error", ["appointment date is not one of the event's days"])
    ends = starts + timedelta(minutes=day.slot_minutes)

    if existing is not None:
        time_changed = _as_naive(existing.starts_at) != starts
        status_changed = existing.status != target_status
        notes_changed = (existing.notes or "") != (fields.notes or "")
        if not (time_changed or status_changed or notes_changed):
            return BookingOutcome("ok", [], appointment=existing, created=False, appointment_changed=False)

        check = validate_appointment_slot(
            event, starts, ends, db, exclude_appointment_id=existing.id, ignore_capacity=(target_status == "cancelled")
        )
        if not check.ok:
            return BookingOutcome("flagged", [check.error or "slot validation failed"])

        before = _appt_snapshot(existing)
        existing.starts_at = starts
        existing.ends_at = ends
        existing.status = target_status
        existing.notes = fields.notes
        db.add(existing)
        audit_calls = [
            dict(
                actor=user,
                action="appointment.import_updated",
                entity_type="appointment",
                entity_id=existing.id,
                before=before,
                after=_appt_snapshot(existing),
            )
        ]
        if target_status != "cancelled":
            customer.stage = "appointment_booked"
            db.add(customer)
        return BookingOutcome("ok", [], appointment=existing, created=False, appointment_changed=True, pending_audit_calls=audit_calls)

    check = validate_appointment_slot(event, starts, ends, db, ignore_capacity=(target_status == "cancelled"))
    if not check.ok:
        return BookingOutcome("flagged", [check.error or "slot validation failed"])

    audit_calls = []
    deal = _resolve_deal_for_import(db, customer, event, user, audit_calls)
    appt = Appointment(
        event_id=event.id,
        customer_id=customer.id,
        deal_id=deal.id if deal is not None else None,
        assigned_user_id=user.id,
        starts_at=starts,
        ends_at=ends,
        appointment_type="consultation",
        status=target_status,
        notes=fields.notes,
    )
    db.add(appt)
    db.flush()
    state.simulated_appointment_rows[appt.id] = row_number
    audit_calls.append(
        dict(
            actor=user,
            action="appointment.import_created",
            entity_type="appointment",
            entity_id=appt.id,
            after=_appt_snapshot(appt),
        )
    )
    if target_status != "cancelled":
        customer.stage = "appointment_booked"
        db.add(customer)
    return BookingOutcome("ok", [], appointment=appt, created=True, appointment_changed=True, pending_audit_calls=audit_calls)


def process_row(db: Session, *, row: ImportRow, mapping: dict[str, str], event: Event, user: User, state: PreviewState) -> RowOutcome:
    fields = parse_mapped_fields(row.raw_data, mapping)
    if fields.parse_errors:
        return RowOutcome(status="error", reasons=fields.parse_errors)

    candidates = find_customer_candidates(db, user, customer_id=fields.customer_id, phone=fields.phone, email=fields.email)
    resolution = candidates.resolve()
    if resolution.status == "review":
        return RowOutcome(status="flagged", reasons=resolution.reasons)

    nested = db.begin_nested()
    try:
        customer, customer_changed, customer_audit, cust_kind, cust_batch_row = _resolve_or_create_customer(
            db, resolution=resolution, fields=fields, user=user, state=state, row_number=row.row_number
        )
        booking_outcome = _resolve_booking(
            db, event=event, customer=customer, fields=fields, user=user, state=state, row_number=row.row_number
        )
        if booking_outcome.status != "ok":
            nested.rollback()
            return RowOutcome(status=booking_outcome.status, reasons=booking_outcome.reasons)

        if customer_audit:
            record_audit(db, **customer_audit)
        for call in booking_outcome.pending_audit_calls:
            record_audit(db, **call)

        nested.commit()

        if cust_kind == "new":
            match_type = "batch" if cust_batch_row != row.row_number else "none"
        else:
            match_type = resolution.matched_via or "id"

        if booking_outcome.created:
            overall = "created"
        elif customer_changed or booking_outcome.appointment_changed:
            overall = "updated"
        else:
            overall = "unchanged"

        customer_ref = CustomerRef(kind=cust_kind, id=customer.id, batch_row_number=cust_batch_row, display_name=customer.name)
        appointment_ref = None
        if booking_outcome.appointment is not None:
            appt_row = state.simulated_appointment_rows.get(booking_outcome.appointment.id)
            appointment_ref = AppointmentRef(
                kind="new" if appt_row is not None else "existing",
                id=booking_outcome.appointment.id,
                batch_row_number=appt_row,
            )

        return RowOutcome(
            status=overall,
            match_type=match_type,
            customer_ref=customer_ref,
            appointment_ref=appointment_ref,
            customer_changed=customer_changed,
            booking_created=booking_outcome.created,
            booking_updated=(booking_outcome.appointment_changed and not booking_outcome.created),
        )
    except Exception as exc:
        nested.rollback()
        return RowOutcome(status="error", reasons=[str(exc)])


def apply_outcome_to_row(row: ImportRow, outcome: RowOutcome, *, persist_real_ids: bool) -> None:
    row.status = outcome.status
    row.reasons = outcome.reasons
    row.match_type = outcome.match_type

    if outcome.customer_ref and (outcome.customer_ref.kind == "existing" or persist_real_ids):
        row.customer_id = outcome.customer_ref.id
    else:
        row.customer_id = None

    if outcome.appointment_ref and (outcome.appointment_ref.kind == "existing" or persist_real_ids):
        row.appointment_id = outcome.appointment_ref.id
    else:
        row.appointment_id = None

    row.mapped_data = {
        "customer_changed": outcome.customer_changed,
        "booking_created": outcome.booking_created,
        "booking_updated": outcome.booking_updated,
        "customer_name": outcome.customer_ref.display_name if outcome.customer_ref else None,
        "provisional_customer_of_row": (
            outcome.customer_ref.batch_row_number
            if outcome.customer_ref and outcome.customer_ref.kind == "new"
            else None
        ),
        "provisional_appointment_of_row": (
            outcome.appointment_ref.batch_row_number
            if outcome.appointment_ref and outcome.appointment_ref.kind == "new"
            else None
        ),
    }


def recompute_batch_counters(batch: ImportBatch, rows: list[ImportRow]) -> None:
    batch.row_count = len(rows)
    customers_created = customers_updated = duplicates_merged = 0
    bookings_created = bookings_updated = rows_unchanged = rows_flagged = 0
    for r in rows:
        if r.status in ("flagged", "error"):
            rows_flagged += 1
            continue
        md = r.mapped_data or {}
        if r.match_type == "none":
            customers_created += 1
        elif r.match_type == "batch":
            duplicates_merged += 1
        elif md.get("customer_changed"):
            customers_updated += 1
        if md.get("booking_created"):
            bookings_created += 1
        elif md.get("booking_updated"):
            bookings_updated += 1
        if r.status == "unchanged":
            rows_unchanged += 1
    batch.customers_created = customers_created
    batch.customers_updated = customers_updated
    batch.duplicates_merged = duplicates_merged
    batch.bookings_created = bookings_created
    batch.bookings_updated = bookings_updated
    batch.rows_unchanged = rows_unchanged
    batch.rows_flagged = rows_flagged


def batch_summary(batch: ImportBatch) -> dict:
    return {
        "status": batch.status,
        "row_count": batch.row_count,
        "customers_created": batch.customers_created,
        "customers_updated": batch.customers_updated,
        "duplicates_merged": batch.duplicates_merged,
        "bookings_created": batch.bookings_created,
        "bookings_updated": batch.bookings_updated,
        "rows_unchanged": batch.rows_unchanged,
        "rows_flagged": batch.rows_flagged,
    }


# ---------------------------------------------------------------------------
# Preview: simulate the whole batch, then roll back and persist results separately
# ---------------------------------------------------------------------------


def run_preview(db: Session, batch: ImportBatch, *, event: Event, user: User, mapping: dict[str, str]) -> None:
    if batch.status in ("committing", "committed"):
        raise HTTPException(status_code=409, detail=f"Batch is already {batch.status}; it cannot be previewed again")

    rows = (
        db.query(ImportRow)
        .filter(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number.asc())
        .all()
    )
    state = PreviewState()
    outcomes: list[tuple[ImportRow, RowOutcome]] = []
    for row in rows:
        outcome = process_row(db, row=row, mapping=mapping, event=event, user=user, state=state)
        outcomes.append((row, outcome))

    db.rollback()  # undo every business-table write from the whole simulation

    # batch/event/rows are expired after rollback; re-fetch the batch we need to mutate.
    batch = db.get(ImportBatch, batch.id)
    fresh_rows = db.query(ImportRow).filter(ImportRow.batch_id == batch.id).order_by(ImportRow.row_number.asc()).all()
    rows_by_id = {r.id: r for r in fresh_rows}
    for row, outcome in outcomes:
        fresh_row = rows_by_id[row.id]
        apply_outcome_to_row(fresh_row, outcome, persist_real_ids=False)
        db.add(fresh_row)

    batch.mapping = mapping
    recompute_batch_counters(batch, fresh_rows)
    batch.status = "previewed"
    db.add(batch)
    db.commit()


# ---------------------------------------------------------------------------
# Commit: same simulation, kept if nothing goes wrong; safe against repeats/concurrency/crashes
# ---------------------------------------------------------------------------


def current_batch_result(db: Session, batch_id: UUID) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    return batch


def run_commit(db: Session, batch: ImportBatch, *, event: Event, user: User) -> ImportBatch:
    # "previewed" is the normal path; "committing"/"committed" are allowed through so a repeated
    # or racing commit call can be answered safely (see the atomic claim below) instead of 409ing
    # on a batch that's merely in flight or already finished. Anything else (e.g. "uploaded",
    # never previewed, or "failed") must go back through preview first.
    if batch.status not in ("previewed", "committing", "committed"):
        raise HTTPException(
            status_code=409, detail="Import must be previewed (with no pending mapping change) before it can be committed"
        )

    now = datetime.now(timezone.utc)
    claimed = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.id == batch.id,
            sa.or_(
                ImportBatch.status == "previewed",
                sa.and_(
                    ImportBatch.status == "committing",
                    ImportBatch.committing_started_at < now - STUCK_COMMIT_THRESHOLD,
                ),
            ),
        )
        .update({"status": "committing", "committing_started_at": now}, synchronize_session=False)
    )
    db.commit()

    if not claimed:
        return current_batch_result(db, batch.id)

    batch = db.get(ImportBatch, batch.id)
    try:
        lock_event_for_booking(db, event.id)
        state = PreviewState()
        rows = (
            db.query(ImportRow)
            .filter(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.row_number.asc())
            .all()
        )
        for row in rows:
            outcome = process_row(db, row=row, mapping=batch.mapping or {}, event=event, user=user, state=state)
            apply_outcome_to_row(row, outcome, persist_real_ids=True)
            db.add(row)
        recompute_batch_counters(batch, rows)
        batch.status = "committed"
        batch.completed_at = datetime.now(timezone.utc)
        db.add(batch)
        record_audit(
            db,
            actor=user,
            action="import.completed",
            entity_type="import_batch",
            entity_id=batch.id,
            after=batch_summary(batch),
        )
        db.commit()
    except Exception:
        db.rollback()
        batch = db.get(ImportBatch, batch.id)
        batch.status = "failed"
        db.add(batch)
        db.commit()
        raise

    return current_batch_result(db, batch.id)
