"""Built-in messaging automations: appointment confirmation and lead follow-up.

The automations never talk to a provider directly. A periodic tick (see
run_tick) decides what should be sent, writes an AutomationSend row whose
unique dedupe_key makes the decision idempotent, and queues an
OutboundMessage that the existing worker sends through SMTP / Twilio. Later
ticks copy the worker's outcome back onto the AutomationSend row.

Appointment slot times: the Events tab stores each slot's wall-clock time in a
timestamptz column as if it were UTC (the timetable grid reads
starts_at[11:16]). Those wall-clock times are the clinic's UK local times, so
they are shown as-is and labelled with the Europe/London zone (GMT/BST) in
force on that date, never shifted.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.models import (
    Appointment,
    AuditLog,
    AutomationSend,
    ClinicSettings,
    Customer,
    CustomerTag,
    Deal,
    Event,
    Interaction,
    MessagingAutomation,
    OutboundMessage,
    Tag,
    Template,
)
from app.services.appointment_rules import validate_appointment_slot
from app.services.audit import record_audit
from app.services.automation import enqueue_outbound_message
from app.services.message_format import looks_like_html, text_to_html
from app.services.template_render import _TOKEN_RE, render_text

logger = logging.getLogger(__name__)

CONFIRMATION = "appointment_confirmation"
FOLLOWUP = "lead_followup"
AUTOMATION_KEYS = (CONFIRMATION, FOLLOWUP)
CHANNELS = ("email", "whatsapp")

UK_TZ = ZoneInfo("Europe/London")
CONFIRMED_APPOINTMENT_STATUSES = ("booked", "confirmed")
# Staff actions that mean "someone has reached out to this lead" even though no
# message body was logged (e.g. the wa.me chat was opened from the CRM).
MANUAL_CONTACT_AUDIT_ACTIONS = ("whatsapp.chat_opened",)
# If the scheduler was down when a lead became due, don't send a stale follow-up.
FOLLOWUP_MAX_LATENESS = timedelta(hours=48)
WHATSAPP_SESSION_WINDOW = timedelta(hours=24)
MIN_FOLLOWUP_DELAY_MINUTES = 15
MAX_FOLLOWUP_DELAY_MINUTES = 30 * 24 * 60

DEFAULT_TEMPLATE_NAMES = {
    CONFIRMATION: {"main": "auto_appointment_confirmation", "update": "auto_appointment_updated"},
    FOLLOWUP: {"main": "auto_lead_followup"},
}

_CLINIC_FIELDS = ["clinic_name", "clinic_phone", "clinic_email"]
_PATIENT_FIELDS = ["customer_name", "first_name"]
SUPPORTED_FIELDS: dict[str, list[str]] = {
    CONFIRMATION: _PATIENT_FIELDS
    + [
        "appointment_date",
        "appointment_time",
        "appointment_end_time",
        "appointment_timezone",
        "appointment_location",
        "event_name",
    ]
    + _CLINIC_FIELDS,
    FOLLOWUP: _PATIENT_FIELDS + _CLINIC_FIELDS,
}

# Statuses that mean the round still needs a human to look at it.
ATTENTION_STATUSES = ("failed", "needs_review")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_clinic_settings(db: Session) -> ClinicSettings:
    clinic = db.get(ClinicSettings, 1)
    if clinic is None:
        clinic = ClinicSettings(id=1, clinic_name="Health Clinic")
        db.add(clinic)
        db.flush()
    return clinic


def _default_template_id(db: Session, channel: str, name: str | None):
    if not name:
        return None
    tpl = (
        db.query(Template)
        .filter(Template.channel == channel, Template.name == name, Template.language == "und")
        .first()
    )
    return tpl.id if tpl else None


def get_automation(db: Session, key: str) -> MessagingAutomation:
    if key not in AUTOMATION_KEYS:
        raise ValueError(f"Unknown automation: {key}")
    auto = db.get(MessagingAutomation, key)
    if auto is None:
        names = DEFAULT_TEMPLATE_NAMES[key]
        auto = MessagingAutomation(
            key=key,
            is_enabled=False,
            email_enabled=False,
            whatsapp_enabled=False,
            send_updates=True,
            delay_minutes=24 * 60,
            email_template_id=_default_template_id(db, "email", names.get("main")),
            whatsapp_template_id=_default_template_id(db, "whatsapp", names.get("main")),
            update_email_template_id=_default_template_id(db, "email", names.get("update")),
            update_whatsapp_template_id=_default_template_id(db, "whatsapp", names.get("update")),
        )
        db.add(auto)
        db.flush()
    return auto


def enabled_channels(auto: MessagingAutomation) -> list[str]:
    out = []
    if auto.email_enabled:
        out.append("email")
    if auto.whatsapp_enabled:
        out.append("whatsapp")
    return out


# ---------------------------------------------------------------------------
# Contact details and permission
# ---------------------------------------------------------------------------


def normalise_whatsapp_number(phone: str | None) -> str | None:
    """Return an E.164 number, or None if it is missing or its country is ambiguous.

    Accepts +<cc>..., 00<cc>..., or a national number starting with a single 0
    (the CRM's existing DEFAULT_COUNTRY_CODE convention). Bare digits without a
    prefix are rejected: we can't tell whether they already include a country code.
    """
    s = (phone or "").strip()
    if s.lower().startswith("whatsapp:"):
        s = s.split(":", 1)[1].strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if s.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = re.sub(r"\D", "", settings.default_country_code or "") + digits[1:]
    else:
        return None
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def is_valid_email(email: str | None) -> bool:
    if not email or not email.strip():
        return False
    try:
        validate_email(email.strip(), check_deliverability=False)
    except EmailNotValidError:
        return False
    return True


_CHANNEL_LABEL = {"email": "Email", "whatsapp": "WhatsApp"}


def channel_block_reason(customer: Customer, channel: str) -> str | None:
    """Why this patient can't be messaged on this channel, or None if they can."""
    # Contact details left on a lead form count as permission; the opt-out is can_contact.
    if customer.can_contact is False:
        return "Patient has opted out of contact"
    if channel == "email":
        if not is_valid_email(customer.email):
            return "No valid email address on file"
        return None
    if normalise_whatsapp_number(customer.phone) is None:
        return "No valid WhatsApp number on file (use international format, e.g. +44...)"
    return None


# ---------------------------------------------------------------------------
# Appointment slot (Events tab is the source of truth)
# ---------------------------------------------------------------------------


@dataclass
class SlotDetails:
    date_text: str
    start_text: str
    end_text: str
    timezone_text: str
    location: str
    event_name: str


def _wall_clock(value: datetime) -> datetime:
    """Naive wall-clock time exactly as the Events grid shows it."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def _uk_local(naive: datetime) -> datetime | None:
    """Attach Europe/London, or None when the time is skipped/repeated by a clock change."""
    first = naive.replace(tzinfo=UK_TZ, fold=0)
    second = naive.replace(tzinfo=UK_TZ, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    return first


def resolve_slot(db: Session, appt: Appointment) -> tuple[SlotDetails | None, str | None]:
    event: Event | None = appt.event
    if event is None:
        return None, "Booking is not linked to an event slot"
    if not event.is_active:
        return None, f"Event '{event.name}' is inactive"
    if appt.starts_at is None or appt.ends_at is None:
        return None, "Booking has no start or end time"
    check = validate_appointment_slot(event, appt.starts_at, appt.ends_at, db, ignore_capacity=True)
    if not check.ok:
        return None, f"Booking does not match a slot in the Events tab: {check.error}"
    location = (event.location or "").strip()
    if not location:
        return None, f"Event '{event.name}' has no location or online-call details"
    start = _uk_local(_wall_clock(appt.starts_at))
    end = _uk_local(_wall_clock(appt.ends_at))
    if start is None or end is None:
        return None, "Slot falls in the hour the UK clocks change, so the time is ambiguous"
    return (
        SlotDetails(
            date_text=f"{start:%A} {start.day} {start:%B %Y}",
            start_text=f"{start:%H:%M}",
            end_text=f"{end:%H:%M}",
            timezone_text=f"UK time, {start.tzname()}",
            location=location,
            event_name=event.name,
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def template_tokens(*texts: str | None) -> list[str]:
    seen: list[str] = []
    for text in texts:
        for match in _TOKEN_RE.finditer(text or ""):
            if match.group(1) not in seen:
                seen.append(match.group(1))
    return seen


def _resolve_language_variant(db: Session, tpl: Template, customer: Customer) -> Template:
    lang = (customer.language or "").strip().lower()
    if not lang or lang == tpl.language:
        return tpl
    variant = (
        db.query(Template)
        .filter(Template.channel == tpl.channel, Template.name == tpl.name, Template.language == lang)
        .first()
    )
    return variant or tpl


def _patient_context(customer: Customer, clinic: ClinicSettings) -> dict[str, str]:
    name = (customer.name or "").strip()
    return {
        "customer_name": name,
        "first_name": name.split()[0] if name else "there",
        "clinic_name": (clinic.clinic_name or "Health Clinic").strip(),
        "clinic_phone": (clinic.contact_phone or "").strip(),
        "clinic_email": (clinic.contact_email or "").strip(),
    }


def _confirmation_context(customer: Customer, clinic: ClinicSettings, slot: SlotDetails) -> dict[str, str]:
    return {
        **_patient_context(customer, clinic),
        "appointment_date": slot.date_text,
        "appointment_time": slot.start_text,
        "appointment_end_time": slot.end_text,
        "appointment_timezone": slot.timezone_text,
        "appointment_location": slot.location,
        "event_name": slot.event_name,
    }


@dataclass
class Rendered:
    template_id: Any
    subject: str | None
    body: str
    outbound_template_id: Any
    outbound_body: str | None
    outbound_variables: dict[str, Any] | None


def _has_recent_inbound_whatsapp(db: Session, customer: Customer, now: datetime) -> bool:
    return (
        db.query(Interaction.id)
        .filter(
            Interaction.customer_id == customer.id,
            Interaction.channel == "whatsapp",
            Interaction.direction == "inbound",
            Interaction.occurred_at >= now - WHATSAPP_SESSION_WINDOW,
        )
        .first()
        is not None
    )


def render_for_channel(
    db: Session,
    *,
    automation_key: str,
    channel: str,
    template_id,
    customer: Customer,
    context: dict[str, str],
    now: datetime,
) -> tuple[Rendered | None, str | None]:
    label = _CHANNEL_LABEL[channel]
    tpl = db.get(Template, template_id) if template_id else None
    if tpl is None:
        return None, f"No {label} template selected for this automation"
    if tpl.channel != channel:
        return None, f"Template '{tpl.name}' is not a {label} template"
    tpl = _resolve_language_variant(db, tpl, customer)

    subject_src = tpl.subject if channel == "email" else None
    tokens = template_tokens(subject_src, tpl.body)
    unsupported = [t for t in tokens if t not in SUPPORTED_FIELDS[automation_key]]
    if unsupported:
        return None, f"Template '{tpl.name}' uses unsupported field(s): {', '.join(unsupported)}"
    empty = [t for t in tokens if not str(context.get(t) or "").strip()]
    if empty:
        return None, f"Template '{tpl.name}' needs value(s) that are missing: {', '.join(empty)}"

    if channel == "email":
        subject = render_text(subject_src or "", context).strip()
        if not subject:
            return None, f"Email template '{tpl.name}' has no subject"
        if looks_like_html(tpl.body):
            # Older HTML template: the worker drops these variables straight into HTML, so escape them.
            variables = {k: html.escape(str(context[k]), quote=False) for k in tokens}
            body = render_text(tpl.body, variables)
        else:
            # Plain-text template: the worker formats it as HTML (and escapes it) at send time.
            variables = {k: str(context[k]) for k in tokens}
            body = text_to_html(render_text(tpl.body, variables))
        return Rendered(tpl.id, subject, body, tpl.id, None, variables), None

    body = render_text(tpl.body, context).strip()
    if tpl.provider_template_id:
        # Approved Twilio Content template: its numbered placeholders follow the
        # order the {{fields}} appear in the CRM copy of the template.
        positional = {str(i + 1): str(context[t]) for i, t in enumerate(template_tokens(tpl.body))}
        return Rendered(tpl.id, None, body, tpl.id, None, positional), None
    if not _has_recent_inbound_whatsapp(db, customer, now):
        return None, (
            f"WhatsApp template '{tpl.name}' has no approved Twilio Content SID. WhatsApp only allows "
            "free-form messages within 24 hours of the patient's last message"
        )
    return Rendered(tpl.id, None, body, None, body, None), None


# ---------------------------------------------------------------------------
# Send log helpers
# ---------------------------------------------------------------------------


def _add_send(db: Session, **fields) -> AutomationSend | None:
    """Insert a send row, or return None if this dedupe_key was already handled."""
    send = AutomationSend(**fields)
    try:
        with db.begin_nested():
            db.add(send)
            db.flush()
    except IntegrityError:
        return None
    return send


def _dispatch(
    db: Session,
    *,
    auto: MessagingAutomation,
    kind: str,
    customer: Customer,
    dedupe_prefix: str,
    revision: int,
    appointment: Appointment | None,
    context: dict[str, str] | None,
    now: datetime,
) -> list[AutomationSend]:
    """Decide and record each enabled channel for one round."""
    created: list[AutomationSend] = []
    for channel in enabled_channels(auto):
        base = dict(
            automation_key=auto.key,
            dedupe_key=f"{dedupe_prefix}:r{revision}:{channel}",
            kind=kind,
            customer_id=customer.id,
            appointment_id=appointment.id if appointment else None,
            revision=revision,
            channel=channel,
            slot_starts_at=appointment.starts_at if appointment else None,
            slot_ends_at=appointment.ends_at if appointment else None,
            created_at=now,
            updated_at=now,
        )
        block = channel_block_reason(customer, channel)
        if block:
            send = _add_send(db, **base, status="skipped", reason=block)
            if send:
                created.append(send)
            continue

        if kind == "update":
            template_id = auto.update_email_template_id if channel == "email" else auto.update_whatsapp_template_id
        else:
            template_id = auto.email_template_id if channel == "email" else auto.whatsapp_template_id
        rendered, problem = render_for_channel(
            db,
            automation_key=auto.key,
            channel=channel,
            template_id=template_id,
            customer=customer,
            context=context or {},
            now=now,
        )
        if problem:
            send = _add_send(db, **base, status="needs_review", reason=problem, template_id=template_id)
            if send:
                created.append(send)
            continue

        # Claim the dedupe key before queueing so a duplicate can never be queued.
        send = _add_send(
            db,
            **base,
            status="queued",
            template_id=rendered.template_id,
            rendered_subject=rendered.subject,
            rendered_body=rendered.body,
            attempted_at=now,
        )
        if send is None:
            continue
        msg = enqueue_outbound_message(
            db,
            owner_user_id=customer.owner_user_id,
            customer_id=customer.id,
            channel=channel,
            template_id=rendered.outbound_template_id,
            body=rendered.outbound_body,
            variables=rendered.outbound_variables,
        )
        db.flush()
        send.outbound_message_id = msg.id
        created.append(send)
    return created


def _add_round_entry(db: Session, *, auto_key: str, kind: str, customer: Customer, dedupe_prefix: str, revision: int,
                     appointment: Appointment | None, status: str, reason: str, now: datetime) -> AutomationSend | None:
    return _add_send(
        db,
        automation_key=auto_key,
        dedupe_key=f"{dedupe_prefix}:r{revision}:round",
        kind=kind,
        customer_id=customer.id,
        appointment_id=appointment.id if appointment else None,
        revision=revision,
        channel=None,
        status=status,
        reason=reason,
        slot_starts_at=appointment.starts_at if appointment else None,
        slot_ends_at=appointment.ends_at if appointment else None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Automation 1: appointment confirmation
# ---------------------------------------------------------------------------


def _appointment_is_confirmed(appt: Appointment | None) -> bool:
    return appt is not None and (appt.status or "").lower() in CONFIRMED_APPOINTMENT_STATUSES


def process_appointment(db: Session, auto: MessagingAutomation, clinic: ClinicSettings, appt: Appointment, now: datetime) -> list[AutomationSend]:
    customer = appt.customer
    if customer is None or not _appointment_is_confirmed(appt):
        return []
    prefix = f"{CONFIRMATION}:{appt.id}"
    sends = (
        db.query(AutomationSend)
        .filter(AutomationSend.automation_key == CONFIRMATION, AutomationSend.appointment_id == appt.id)
        .order_by(AutomationSend.revision.asc(), AutomationSend.created_at.asc())
        .all()
    )
    latest_rev = max((s.revision for s in sends), default=0)
    latest = [s for s in sends if s.revision == latest_rev]
    same_slot = bool(latest) and latest[0].slot_starts_at == appt.starts_at and latest[0].slot_ends_at == appt.ends_at

    if same_slot:
        # This exact slot was already handled. The only thing left to do is
        # retry a round that was held back for staff review.
        review = next((s for s in latest if s.channel is None and s.status == "needs_review"), None)
        if review is None:
            return []
        slot, problem = resolve_slot(db, appt)
        if problem:
            if review.reason != problem:
                review.reason = problem
                review.updated_at = now
            return []
        review.status = "resolved"
        review.reason = f"{review.reason} (resolved; confirmation sent)"
        review.updated_at = now
        return _dispatch(db, auto=auto, kind=review.kind, customer=customer, dedupe_prefix=prefix, revision=latest_rev,
                         appointment=appt, context=_confirmation_context(customer, clinic, slot), now=now)

    if not sends:
        # Never back-fill bookings made before the automation was switched on.
        if auto.active_since is None or appt.created_at is None or appt.created_at < auto.active_since:
            return []
        kind = "confirmation"
        deal: Deal | None = appt.deal
        if deal is not None and deal.confirmation_sent_at is not None and deal.confirmation_sent_at >= appt.created_at:
            entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=kind, customer=customer, dedupe_prefix=prefix,
                                     revision=1, appointment=appt, status="skipped",
                                     reason="Staff had already confirmed this booking", now=now)
            return [entry] if entry else []
    else:
        delivered = any(s.status in ("queued", "sent") and s.channel is not None for s in sends)
        kind = "update" if delivered else "confirmation"
        # Earlier rounds that were waiting for review are now out of date.
        for s in sends:
            if s.status == "needs_review":
                s.status = "resolved"
                s.reason = f"{s.reason} (superseded: booking moved to a new slot)"
                s.updated_at = now

    revision = latest_rev + 1
    if kind == "update" and not auto.send_updates:
        entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=kind, customer=customer, dedupe_prefix=prefix,
                                 revision=revision, appointment=appt, status="skipped",
                                 reason="Booking moved to a new slot; updated confirmations are switched off", now=now)
        return [entry] if entry else []

    slot, problem = resolve_slot(db, appt)
    if problem:
        entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=kind, customer=customer, dedupe_prefix=prefix,
                                 revision=revision, appointment=appt, status="needs_review", reason=problem, now=now)
        return [entry] if entry else []
    return _dispatch(db, auto=auto, kind=kind, customer=customer, dedupe_prefix=prefix, revision=revision,
                     appointment=appt, context=_confirmation_context(customer, clinic, slot), now=now)


def _upcoming_confirmed_appointments(db: Session, now: datetime) -> list[Appointment]:
    # starts_at holds UK wall-clock time stored as UTC, so compare against UK "now" the same way.
    uk_now_as_stored = now.astimezone(UK_TZ).replace(tzinfo=timezone.utc)
    return (
        db.query(Appointment)
        .options(joinedload(Appointment.event).joinedload(Event.days), joinedload(Appointment.customer), joinedload(Appointment.deal))
        .filter(Appointment.status.in_(CONFIRMED_APPOINTMENT_STATUSES))
        .filter(Appointment.starts_at > uk_now_as_stored)
        .order_by(Appointment.created_at.asc())
        .all()
    )


def _queued_anything(sends: list[AutomationSend]) -> int:
    """1 if this patient was actually messaged (skips and reviews don't use up the limit)."""
    return 1 if any(s.status == "queued" for s in sends) else 0


def process_confirmations(db: Session, now: datetime) -> int:
    auto = get_automation(db, CONFIRMATION)
    if not auto.is_enabled or not enabled_channels(auto):
        return 0
    clinic = get_clinic_settings(db)
    count = 0
    messaged = 0
    for appt in _upcoming_confirmed_appointments(db, now):
        if auto.max_per_run and messaged >= auto.max_per_run:
            break  # the rest wait for the next check
        try:
            sends = process_appointment(db, auto, clinic, appt, now)
            count += len(sends)
            messaged += _queued_anything(sends)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Appointment confirmation failed for appointment %s", appt.id)
    return count


# ---------------------------------------------------------------------------
# Automation 2: follow up with leads who have not booked
# ---------------------------------------------------------------------------


def followup_block_reason(db: Session, customer: Customer, *, ignore_outbound_ids: Iterable = ()) -> str | None:
    """Why this lead must not get the automated follow-up, or None if eligible."""
    if customer.can_contact is False:
        return "Lead has opted out of contact"
    is_test = (
        db.query(CustomerTag.id)
        .join(Tag, Tag.id == CustomerTag.tag_id)
        .filter(CustomerTag.customer_id == customer.id, Tag.name == "test_lead")
        .first()
    )
    if is_test:
        return "Test lead"
    if (customer.stage or "new") != "new":
        return f"Lead is no longer new (stage: {customer.stage})"
    if (
        db.query(Appointment.id)
        .filter(Appointment.customer_id == customer.id, Appointment.status != "cancelled")
        .first()
    ):
        return "Lead has an appointment"
    outbound = (
        db.query(Interaction.channel)
        .filter(Interaction.customer_id == customer.id, Interaction.direction == "outbound")
        .first()
    )
    if outbound:
        return f"Lead has already been contacted (outbound {outbound[0]} logged)"
    q = db.query(OutboundMessage.id).filter(OutboundMessage.customer_id == customer.id, OutboundMessage.status != "cancelled")
    ignore = [i for i in ignore_outbound_ids if i is not None]
    if ignore:
        q = q.filter(OutboundMessage.id.notin_(ignore))
    if q.first():
        return "A message to this lead is already queued or sent"
    if db.query(Deal.id).filter(Deal.customer_id == customer.id, Deal.confirmation_sent_at.isnot(None)).first():
        return "Lead has been sent an appointment confirmation"
    if (
        db.query(AuditLog.id)
        .filter(
            AuditLog.entity_type == "customer",
            AuditLog.entity_id == customer.id,
            AuditLog.action.in_(MANUAL_CONTACT_AUDIT_ACTIONS),
        )
        .first()
    ):
        return "Staff opened a WhatsApp chat with this lead"
    return None


def process_lead(db: Session, auto: MessagingAutomation, clinic: ClinicSettings, customer: Customer, now: datetime) -> list[AutomationSend]:
    prefix = f"{FOLLOWUP}:{customer.id}"
    due_at = customer.created_at + timedelta(minutes=auto.delay_minutes)
    if due_at > now:
        return []
    if now - due_at > FOLLOWUP_MAX_LATENESS:
        reason = "Follow-up window missed (lead became due while automations weren't running)"
    else:
        reason = followup_block_reason(db, customer)
    if reason:
        entry = _add_round_entry(db, auto_key=FOLLOWUP, kind="followup", customer=customer, dedupe_prefix=prefix,
                                 revision=1, appointment=None, status="skipped", reason=reason, now=now)
        return [entry] if entry else []
    return _dispatch(db, auto=auto, kind="followup", customer=customer, dedupe_prefix=prefix, revision=1,
                     appointment=None, context=_patient_context(customer, clinic), now=now)


def process_followups(db: Session, now: datetime, *, batch_size: int = 200) -> int:
    auto = get_automation(db, FOLLOWUP)
    if not auto.is_enabled or not enabled_channels(auto) or auto.active_since is None:
        return 0
    clinic = get_clinic_settings(db)
    already = sa.exists().where(AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == Customer.id)
    due = (
        db.query(Customer)
        .filter(Customer.created_at >= auto.active_since)
        .filter(Customer.created_at <= now - timedelta(minutes=auto.delay_minutes))
        .filter(~already)
        .order_by(Customer.created_at.asc())
        .limit(batch_size)
        .all()
    )
    count = 0
    messaged = 0
    for customer in due:
        if auto.max_per_run and messaged >= auto.max_per_run:
            break  # the rest wait for the next check
        try:
            sends = process_lead(db, auto, clinic, customer, now)
            count += len(sends)
            messaged += _queued_anything(sends)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Lead follow-up failed for customer %s", customer.id)
    return count


# ---------------------------------------------------------------------------
# Outcome sync and last-moment guard
# ---------------------------------------------------------------------------


def _cancel_queued(db: Session, send: AutomationSend, reason: str, now: datetime) -> bool:
    """Cancel the outbound message if the worker hasn't claimed it yet."""
    claimed = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.id == send.outbound_message_id, OutboundMessage.status == "queued")
        .update({OutboundMessage.status: "cancelled", OutboundMessage.cancelled_at: now, OutboundMessage.updated_at: now},
                synchronize_session=False)
    )
    if claimed != 1:
        return False
    send.status = "cancelled"
    send.reason = reason
    send.updated_at = now
    return True


def _still_wanted(db: Session, send: AutomationSend) -> str | None:
    """Re-check a queued send just before the worker picks it up."""
    customer = db.get(Customer, send.customer_id)
    if customer is None:
        return "Patient record was deleted"
    block = channel_block_reason(customer, send.channel) if send.channel else None
    if block:
        return block
    if send.automation_key == CONFIRMATION:
        appt = db.get(Appointment, send.appointment_id) if send.appointment_id else None
        if not _appointment_is_confirmed(appt):
            return "Booking was cancelled or removed before the message was sent"
        if appt.starts_at != send.slot_starts_at or appt.ends_at != send.slot_ends_at:
            return "Booking moved to a new slot before the message was sent"
        return None
    own = [
        s.outbound_message_id
        for s in db.query(AutomationSend).filter(AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == customer.id)
    ]
    return followup_block_reason(db, customer, ignore_outbound_ids=own)


def _record_confirmation_on_deal(db: Session, send: AutomationSend) -> None:
    appt = db.get(Appointment, send.appointment_id) if send.appointment_id else None
    deal = appt.deal if appt is not None else None
    if deal is not None:
        deal.confirmation_sent_at = send.sent_at
        deal.confirmation_channel = f"auto_{send.channel}"
        deal.confirmation_template_id = send.template_id
    customer = db.get(Customer, send.customer_id)
    record_audit(
        db,
        actor=None,
        action="appointment.confirmation_sent" if send.kind == "confirmation" else "appointment.update_sent",
        entity_type="customer",
        entity_id=send.customer_id,
        after={"channel": send.channel, "automated": True, "slot_starts_at": send.slot_starts_at.isoformat() if send.slot_starts_at else None},
        metadata={"customer_id": str(send.customer_id), "customer_name": customer.name if customer else None, "automation_send_id": str(send.id)},
    )


def sync_outcomes(db: Session, now: datetime) -> int:
    changed = 0
    queued = (
        db.query(AutomationSend)
        .options(joinedload(AutomationSend.outbound_message))
        .filter(AutomationSend.status == "queued")
        .all()
    )
    for send in queued:
        msg = send.outbound_message
        if msg is None:
            send.status, send.reason = "failed", "Queued message was deleted before it was sent"
        elif msg.status == "sent":
            send.status = "sent"
            send.sent_at = msg.updated_at or now
            send.reason = None
            if send.automation_key == CONFIRMATION:
                _record_confirmation_on_deal(db, send)
        elif msg.status == "failed":
            send.status, send.reason = "failed", msg.last_error or "Provider rejected the message"
        elif msg.status == "cancelled":
            send.status, send.reason = "cancelled", send.reason or "Message was cancelled before sending"
        elif msg.status == "queued":
            reason = _still_wanted(db, send)
            if not (reason and _cancel_queued(db, send, reason, now)):
                continue
        else:
            continue  # 'sending': the worker owns it right now
        send.updated_at = now
        changed += 1
    db.commit()
    return changed


# ---------------------------------------------------------------------------
# Tick + background scheduler
# ---------------------------------------------------------------------------


def run_tick(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or _now()
    synced = sync_outcomes(db, now)
    confirmations = process_confirmations(db, now)
    followups = process_followups(db, now)
    db.commit()
    return {"synced": synced, "confirmation_decisions": confirmations, "followup_decisions": followups}


_TICK_LOCK_ID = 7_310_042  # arbitrary, app-wide advisory lock id for the automation tick
_scheduler_started = False


def run_tick_exclusive(now: datetime | None = None) -> dict[str, int] | None:
    """Run one tick unless another process is already running one."""
    from app.db.session import SessionLocal, engine

    with engine.connect() as lock_conn:
        got = lock_conn.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": _TICK_LOCK_ID}).scalar()
        if not got:
            return None
        try:
            db = SessionLocal()
            try:
                return run_tick(db, now)
            finally:
                db.close()
        finally:
            lock_conn.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": _TICK_LOCK_ID})
            lock_conn.commit()


def _scheduler_loop() -> None:
    interval = max(10, settings.automations_tick_seconds)
    while True:
        try:
            run_tick_exclusive()
        except Exception:
            logger.exception("Messaging automation tick failed")
        time.sleep(interval)


def start_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started or not settings.automations_scheduler_enabled:
        return
    _scheduler_started = True
    threading.Thread(target=_scheduler_loop, name="messaging-automations", daemon=True).start()
