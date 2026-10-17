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

import hashlib
import html
import json
import logging
import re
import threading
import time
import uuid
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
    User,
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
# If the scheduler was down when a lead became due, don't send a stale follow-up.
FOLLOWUP_MAX_LATENESS = timedelta(hours=48)
MIN_FOLLOWUP_DELAY_MINUTES = 15
MAX_FOLLOWUP_DELAY_MINUTES = 30 * 24 * 60

DEFAULT_TEMPLATE_NAMES = {
    CONFIRMATION: {"main": "auto_appointment_confirmation", "update": "auto_appointment_updated"},
    FOLLOWUP: {"main": "auto_lead_followup"},
}

_CLINIC_FIELDS = ["clinic_name", "clinic_phone", "clinic_email"]
_PATIENT_FIELDS = ["customer_name", "first_name"]
# Fields resolved from the person's event booking (Appointment -> Event / EventDay).
BOOKING_FIELDS = ["event_date", "slot", "event_venue", "event_name"]
# Older names for the same booking values, still accepted in templates.
LEGACY_BOOKING_FIELDS = [
    "appointment_date",
    "appointment_time",
    "appointment_end_time",
    "appointment_timezone",
    "appointment_location",
    "event_location",
    "location",
]
# Shown to staff (Insert field menu, "Fields you can use").
SUPPORTED_FIELDS: dict[str, list[str]] = {
    CONFIRMATION: ["first_name", "customer_name"] + BOOKING_FIELDS + _CLINIC_FIELDS,
    FOLLOWUP: _PATIENT_FIELDS + _CLINIC_FIELDS,
}
# Everything a template may use without being held for review.
ACCEPTED_FIELDS: dict[str, set[str]] = {
    CONFIRMATION: set(SUPPORTED_FIELDS[CONFIRMATION]) | set(LEGACY_BOOKING_FIELDS),
    FOLLOWUP: set(SUPPORTED_FIELDS[FOLLOWUP]),
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


def booking_values(slot: SlotDetails) -> dict[str, str]:
    """Merge-field values for one resolved event booking, in UK time."""
    return {
        "event_date": slot.date_text,
        "slot": f"{slot.start_text} to {slot.end_text} ({slot.timezone_text})",
        "event_venue": slot.location,
        "event_name": slot.event_name,
        "appointment_date": slot.date_text,
        "appointment_time": slot.start_text,
        "appointment_end_time": slot.end_text,
        "appointment_timezone": slot.timezone_text,
        "appointment_location": slot.location,
        "event_location": slot.location,
        "location": slot.location,
    }


def _confirmation_context(customer: Customer, clinic: ClinicSettings, slot: SlotDetails) -> dict[str, str]:
    return {**_patient_context(customer, clinic), **booking_values(slot)}


def _uk_now_as_stored(now: datetime) -> datetime:
    # starts_at holds UK wall-clock time stored as UTC, so compare against UK "now" the same way.
    return now.astimezone(UK_TZ).replace(tzinfo=timezone.utc)


def resolve_customer_booking(
    db: Session, customer: Customer, *, appointment_id=None, now: datetime | None = None
) -> tuple[Appointment | None, SlotDetails | None, str | None]:
    """The person's upcoming event booking and its slot details, or why there isn't a usable one.

    For manual sends only; the automation always uses the exact booking that triggered it.
    With appointment_id, that booking is used. Without it, the person must have exactly one
    upcoming active booking; with several, nothing is guessed. Only an Appointment row (a person booked into a specific slot of an event in the
    Events tab) counts. Being a lead, having an event on their deal, or being at the
    "appointment booked" pipeline stage without a slot does not.
    """
    now = now or _now()
    who = (customer.name or "This person").strip()
    q = (
        db.query(Appointment)
        .options(joinedload(Appointment.event).joinedload(Event.days))
        .filter(Appointment.customer_id == customer.id)
    )
    if appointment_id is not None:
        appt = q.filter(Appointment.id == appointment_id).first()
        if appt is None:
            return None, None, "That booking was not found"
        if not _appointment_is_confirmed(appt):
            return None, None, f"{who}'s booking is {appt.status}, not booked"
    else:
        upcoming = (
            q.filter(Appointment.status.in_(CONFIRMED_APPOINTMENT_STATUSES), Appointment.starts_at > _uk_now_as_stored(now))
            .order_by(Appointment.starts_at.asc())
            .all()
        )
        if len(upcoming) > 1:
            # Never guess which booking a message is about.
            listed = "; ".join(
                f"{a.event.name if a.event else 'event'} on {_wall_clock(a.starts_at):%a %d %b %H:%M}" for a in upcoming
            )
            return None, None, f"{who} has {len(upcoming)} upcoming event bookings ({listed}), so it's unclear which one this message is about"
        appt = upcoming[0] if upcoming else None
    if appt is None:
        assigned = (
            db.query(Event.name)
            .join(Deal, Deal.event_id == Event.id)
            .filter(Deal.customer_id == customer.id)
            .first()
        )
        if assigned:
            return None, None, f"{who} is linked to the event '{assigned[0]}' but has no booked time slot in the Events tab"
        return None, None, f"{who} isn't booked into an upcoming event slot in the Events tab"
    slot, problem = resolve_slot(db, appt)
    return appt, slot, problem


@dataclass
class Rendered:
    template_id: Any
    subject: str | None
    body: str
    outbound_template_id: Any
    outbound_body: str | None
    outbound_variables: dict[str, Any] | None

    def payload(self) -> dict[str, Any]:
        return {
            "template_id": str(self.outbound_template_id) if self.outbound_template_id else None,
            "body": self.outbound_body,
            "variables": self.outbound_variables,
        }


def render_for_channel(
    db: Session,
    *,
    automation_key: str,
    channel: str,
    template_id,
    customer: Customer,
    context: dict[str, str],
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
    unsupported = [t for t in tokens if t not in ACCEPTED_FIELDS[automation_key]]
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

    # Automated WhatsApp always goes through an approved Twilio Content template; there is
    # no free-form fallback (manual replies from the Inbox are separate and unaffected).
    if not tpl.provider_template_id:
        return None, (
            f"WhatsApp template '{tpl.name}' has no Twilio Content SID. Automated WhatsApp messages "
            "need a template approved by WhatsApp"
        )
    if tpl.provider_approved_at is None:
        return None, (
            f"WhatsApp template '{tpl.name}' isn't marked as approved by WhatsApp yet. Tick it as approved "
            "once Twilio shows the template as approved"
        )
    body = render_text(tpl.body, context).strip()
    # Its numbered placeholders follow the order the {{fields}} appear in the CRM copy.
    positional = {str(i + 1): str(context[t]) for i, t in enumerate(template_tokens(tpl.body))}
    return Rendered(tpl.id, None, body, tpl.id, None, positional), None


# ---------------------------------------------------------------------------
# Planning: the same rendering is used for previews, approvals and real sends
# ---------------------------------------------------------------------------


@dataclass
class ChannelPlan:
    channel: str
    address: str | None
    status: str  # "ok" | "skipped" | "needs_review"
    reason: str | None
    template_id: Any
    rendered: Rendered | None


def _template_id_for(auto: MessagingAutomation, kind: str, channel: str):
    if kind == "update":
        return auto.update_email_template_id if channel == "email" else auto.update_whatsapp_template_id
    return auto.email_template_id if channel == "email" else auto.whatsapp_template_id


def channel_address(customer: Customer, channel: str) -> str | None:
    if channel == "email":
        return (customer.email or "").strip() or None
    return normalise_whatsapp_number(customer.phone) or ((customer.phone or "").strip() or None)


def plan_channels(db: Session, auto: MessagingAutomation, kind: str, customer: Customer, context: dict[str, str]) -> list[ChannelPlan]:
    """What each enabled channel would send right now. Writes nothing."""
    plans = []
    for channel in enabled_channels(auto):
        template_id = _template_id_for(auto, kind, channel)
        address = channel_address(customer, channel)
        block = channel_block_reason(customer, channel)
        if block:
            plans.append(ChannelPlan(channel, address, "skipped", block, template_id, None))
            continue
        rendered, problem = render_for_channel(
            db, automation_key=auto.key, channel=channel, template_id=template_id, customer=customer, context=context
        )
        if problem:
            plans.append(ChannelPlan(channel, address, "needs_review", problem, template_id, None))
        else:
            plans.append(ChannelPlan(channel, address, "ok", None, rendered.template_id, rendered))
    return plans


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


def _audit_send(db: Session, send: AutomationSend, action: str, *, actor: User | None = None, note: str | None = None) -> None:
    customer = db.get(Customer, send.customer_id)
    record_audit(
        db,
        actor=actor,
        action=action,
        entity_type="customer",
        entity_id=send.customer_id,
        after={"automation": send.automation_key, "kind": send.kind, "channel": send.channel, "status": send.status, "reason": send.reason or note},
        metadata={"customer_id": str(send.customer_id), "customer_name": customer.name if customer else None, "automation_send_id": str(send.id)},
    )


def _enqueue(db: Session, send: AutomationSend, customer: Customer, now: datetime) -> OutboundMessage:
    """Hand the stored payload to the worker unchanged."""
    payload = send.payload or {}
    msg = enqueue_outbound_message(
        db,
        owner_user_id=customer.owner_user_id,
        customer_id=customer.id,
        channel=send.channel,
        template_id=uuid.UUID(payload["template_id"]) if payload.get("template_id") else None,
        body=payload.get("body"),
        variables=payload.get("variables"),
    )
    db.flush()
    send.outbound_message_id = msg.id
    send.status = "queued"
    send.attempted_at = now
    send.updated_at = now
    return msg


BOOKING_SNAPSHOT_FIELDS = ("event_date", "slot", "event_venue")


def _payload_with_booking(rendered: Rendered, context: dict[str, str] | None) -> dict[str, Any]:
    """The worker payload, plus the booking details this message was rendered with."""
    payload = rendered.payload()
    if context is not None:
        payload["booking"] = {k: context.get(k) for k in BOOKING_SNAPSHOT_FIELDS}
    return payload


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
    force_approval: bool = False,
) -> list[AutomationSend]:
    """Record each enabled channel for one round; queue it, or wait for approval."""
    created: list[AutomationSend] = []
    needs_approval = auto.require_approval or force_approval
    for plan in plan_channels(db, auto, kind, customer, context or {}):
        base = dict(
            automation_key=auto.key,
            dedupe_key=f"{dedupe_prefix}:r{revision}:{plan.channel}",
            kind=kind,
            customer_id=customer.id,
            appointment_id=appointment.id if appointment else None,
            revision=revision,
            channel=plan.channel,
            slot_starts_at=appointment.starts_at if appointment else None,
            slot_ends_at=appointment.ends_at if appointment else None,
            template_id=plan.template_id,
            created_at=now,
            updated_at=now,
        )
        if plan.status != "ok":
            send = _add_send(db, **base, status=plan.status, reason=plan.reason)
        else:
            # Claim the dedupe key before queueing so a duplicate can never be queued.
            send = _add_send(
                db,
                **base,
                status="pending_approval",
                rendered_subject=plan.rendered.subject,
                rendered_body=plan.rendered.body,
                payload=_payload_with_booking(plan.rendered, context if appointment else None),
            )
            if send is not None and not needs_approval:
                _enqueue(db, send, customer, now)
        if send is not None:
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


def _round_entry(rows: list[AutomationSend]) -> AutomationSend | None:
    return next((s for s in rows if s.channel is None), None)


# ---------------------------------------------------------------------------
# Automation 1: event booking confirmation
# ---------------------------------------------------------------------------


def _appointment_is_confirmed(appt: Appointment | None) -> bool:
    return appt is not None and (appt.status or "").lower() in CONFIRMED_APPOINTMENT_STATUSES


STAFF_OPEN_STATUSES = ("pending_approval", "reapproval", "held")


@dataclass
class ConfirmationRound:
    sends: list[AutomationSend]
    rows: list[AutomationSend]  # rows of the open round (empty when the round is not created yet)
    kind: str
    revision: int
    is_new: bool


def _confirmation_round(db: Session, appt: Appointment) -> ConfirmationRound:
    """The round for this booking's current slot: the open one, or the one that would be created next."""
    sends = (
        db.query(AutomationSend)
        .filter(AutomationSend.automation_key == CONFIRMATION, AutomationSend.appointment_id == appt.id)
        .order_by(AutomationSend.revision.asc(), AutomationSend.created_at.asc())
        .all()
    )
    latest_rev = max((s.revision for s in sends), default=0)
    latest = [s for s in sends if s.revision == latest_rev]
    # While a round is waiting on staff (approval, re-approval or a hold) it stays the open
    # round even if the booking moves; approval re-renders it with the booking as it is then.
    if any(s.status in STAFF_OPEN_STATUSES for s in latest):
        return ConfirmationRound(sends, latest, latest[0].kind, latest_rev, False)
    # A round whose messages were all cancelled before sending (the booking was cancelled,
    # moved or lost its venue after queueing) doesn't count as handled.
    handled = [s for s in latest if s.status != "cancelled"]
    if handled and handled[0].slot_starts_at == appt.starts_at and handled[0].slot_ends_at == appt.ends_at:
        return ConfirmationRound(sends, latest, handled[0].kind, latest_rev, False)
    delivered = any(s.status in ("queued", "sent") and s.channel is not None for s in sends)
    return ConfirmationRound(sends, [], "update" if delivered else "confirmation", latest_rev + 1, True)


def process_appointment(db: Session, auto: MessagingAutomation, clinic: ClinicSettings, appt: Appointment, now: datetime) -> list[AutomationSend]:
    """Handle exactly this booking (and its slot). Each booking is confirmed on its own."""
    customer = appt.customer
    if customer is None or not _appointment_is_confirmed(appt):
        return []
    prefix = f"{CONFIRMATION}:{appt.id}"
    rnd = _confirmation_round(db, appt)

    if not rnd.is_new:
        entry = _round_entry(rnd.rows)
        # Only a round held back for review, or released from a staff hold, has work left.
        if entry is None or entry.status not in ("needs_review", "released") or any(s.channel for s in rnd.rows):
            return []
        slot, problem = resolve_slot(db, appt)
        if problem:
            entry.status, entry.reason, entry.updated_at = "needs_review", problem, now
            return []
        entry.status = "resolved"
        entry.reason = f"{entry.reason or 'Released by staff'} (resolved; confirmation sent)"
        entry.slot_starts_at, entry.slot_ends_at, entry.updated_at = appt.starts_at, appt.ends_at, now
        return _dispatch(db, auto=auto, kind=rnd.kind, customer=customer, dedupe_prefix=prefix, revision=rnd.revision,
                         appointment=appt, context=_confirmation_context(customer, clinic, slot), now=now)

    if not rnd.sends:
        # Never back-fill bookings made before the automation was switched on.
        if auto.active_since is None or appt.created_at is None or appt.created_at < auto.active_since:
            return []
        deal: Deal | None = appt.deal
        if deal is not None and deal.confirmation_sent_at is not None and deal.confirmation_sent_at >= appt.created_at:
            entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=rnd.kind, customer=customer, dedupe_prefix=prefix,
                                     revision=1, appointment=appt, status="skipped",
                                     reason="Staff had already confirmed this booking", now=now)
            return [entry] if entry else []
    else:
        _supersede_open_rows(db, rnd.sends, now)

    if rnd.kind == "update" and not auto.send_updates:
        entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=rnd.kind, customer=customer, dedupe_prefix=prefix,
                                 revision=rnd.revision, appointment=appt, status="skipped",
                                 reason="Booking moved to a new slot; updated confirmations are switched off", now=now)
        return [entry] if entry else []

    slot, problem = resolve_slot(db, appt)
    if problem:
        entry = _add_round_entry(db, auto_key=CONFIRMATION, kind=rnd.kind, customer=customer, dedupe_prefix=prefix,
                                 revision=rnd.revision, appointment=appt, status="needs_review", reason=problem, now=now)
        return [entry] if entry else []
    return _dispatch(db, auto=auto, kind=rnd.kind, customer=customer, dedupe_prefix=prefix, revision=rnd.revision,
                     appointment=appt, context=_confirmation_context(customer, clinic, slot), now=now)


def _supersede_open_rows(db: Session, sends: list[AutomationSend], now: datetime) -> None:
    """The booking moved: anything still waiting for the old slot is out of date."""
    for s in sends:
        if s.channel is None and s.status in ("needs_review", "held", "released"):
            s.status = "resolved"
            s.reason = f"{s.reason or 'Held by staff'} (superseded: booking moved to a new slot)"
            s.updated_at = now
        elif s.channel is not None and s.status in ("pending_approval", "held", "paused"):
            _cancel_send(db, s, "Booking moved to a new slot before this was sent", now)


def _upcoming_confirmed_appointments(db: Session, now: datetime) -> list[Appointment]:
    return (
        db.query(Appointment)
        .options(joinedload(Appointment.event).joinedload(Event.days), joinedload(Appointment.customer), joinedload(Appointment.deal))
        .filter(Appointment.status.in_(CONFIRMED_APPOINTMENT_STATUSES))
        .filter(Appointment.starts_at > _uk_now_as_stored(now))
        .order_by(Appointment.created_at.asc())
        .all()
    )


def _messaged_anyone(sends: list[AutomationSend]) -> int:
    """1 if this patient was queued or put up for approval (skips and reviews don't use up the limit)."""
    return 1 if any(s.status in ("queued", "pending_approval") for s in sends) else 0


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
            messaged += _messaged_anyone(sends)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Appointment confirmation failed for appointment %s", appt.id)
    return count


# ---------------------------------------------------------------------------
# Automation 2: follow up with leads who have not booked
# ---------------------------------------------------------------------------

PENDING_OUTBOUND_STATUSES = ("queued", "sending")


def followup_status(db: Session, customer: Customer, *, ignore_outbound_ids: Iterable = ()) -> tuple[str, str | None]:
    """("ok" | "wait" | "block", reason) for the automated follow-up.

    block: opted out (do not contact), test lead, has an event booking, or there's been
    actual contact: a logged outbound call/message (internal notes excluded), a message
    the worker sent, or a confirmation sent/marked.
    wait: a staff message is queued but not sent yet; check again once its status changes.
    The pipeline stage doesn't matter, and opening a WhatsApp chat from the CRM is not
    contact (nothing may have been sent). Staff holds and exclusions are handled per
    recipient on the Automations page, not here.
    """
    if customer.can_contact is False:
        return "block", "Lead has opted out of contact"
    is_test = (
        db.query(CustomerTag.id)
        .join(Tag, Tag.id == CustomerTag.tag_id)
        .filter(CustomerTag.customer_id == customer.id, Tag.name == "test_lead")
        .first()
    )
    if is_test:
        return "block", "Test lead"
    if (
        db.query(Appointment.id)
        .filter(Appointment.customer_id == customer.id, Appointment.status != "cancelled")
        .first()
    ):
        return "block", "Lead has an appointment"
    outbound = (
        db.query(Interaction.channel)
        .filter(Interaction.customer_id == customer.id, Interaction.direction == "outbound")
        .filter(sa.func.coalesce(sa.func.lower(Interaction.subject), "") != "internal note")
        .first()
    )
    if outbound:
        return "block", f"Lead has already been contacted (outbound {outbound[0]} logged)"
    ignore = [i for i in ignore_outbound_ids if i is not None]
    msgs = db.query(OutboundMessage.status).filter(OutboundMessage.customer_id == customer.id)
    if ignore:
        msgs = msgs.filter(OutboundMessage.id.notin_(ignore))
    statuses = {row[0] for row in msgs.all()}
    if "sent" in statuses:
        return "block", "A message to this lead has already been sent"
    if db.query(Deal.id).filter(Deal.customer_id == customer.id, Deal.confirmation_sent_at.isnot(None)).first():
        return "block", "Lead has been sent an appointment confirmation"
    if statuses & set(PENDING_OUTBOUND_STATUSES):
        return "wait", "A staff message to this lead is waiting to be sent"
    return "ok", None


def _own_followup_outbound_ids(db: Session, customer_id) -> list:
    return [
        row[0]
        for row in db.query(AutomationSend.outbound_message_id).filter(
            AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == customer_id
        )
    ]


def process_lead(db: Session, auto: MessagingAutomation, clinic: ClinicSettings, customer: Customer, now: datetime) -> list[AutomationSend]:
    prefix = f"{FOLLOWUP}:{customer.id}"
    due_at = customer.created_at + timedelta(minutes=auto.delay_minutes)
    if due_at > now:
        return []
    rows = db.query(AutomationSend).filter(AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == customer.id).all()
    entry = _round_entry(rows)
    if any(s.channel for s in rows) or (entry is not None and entry.status != "released"):
        return []
    released = entry is not None
    if not released and now - due_at > FOLLOWUP_MAX_LATENESS:
        state, reason = "block", "Follow-up window missed (lead became due while automations weren't running)"
    else:
        state, reason = followup_status(db, customer)
    if state == "wait":
        return []  # a staff message is pending; decide on a later check
    if state == "block":
        if entry is not None:
            entry.status, entry.reason, entry.updated_at = "skipped", reason, now
            return [entry]
        entry = _add_round_entry(db, auto_key=FOLLOWUP, kind="followup", customer=customer, dedupe_prefix=prefix,
                                 revision=1, appointment=None, status="skipped", reason=reason, now=now)
        return [entry] if entry else []
    if entry is not None:
        entry.status, entry.reason, entry.updated_at = "resolved", "Released by staff (follow-up sent)", now
    return _dispatch(db, auto=auto, kind="followup", customer=customer, dedupe_prefix=prefix, revision=1,
                     appointment=None, context=_patient_context(customer, clinic), now=now)


def _followup_candidates(db: Session, auto: MessagingAutomation, *, due_before: datetime | None, limit: int):
    """Leads created since the automation was switched on with no follow-up decision yet
    (a lead released from a staff hold counts as undecided)."""
    decided = sa.exists().where(
        AutomationSend.automation_key == FOLLOWUP,
        AutomationSend.customer_id == Customer.id,
        AutomationSend.status != "released",
    )
    q = db.query(Customer).filter(Customer.created_at >= auto.active_since).filter(~decided)
    if due_before is not None:
        q = q.filter(Customer.created_at <= due_before)
    return q.order_by(Customer.created_at.asc()).limit(limit).all()


def process_followups(db: Session, now: datetime, *, batch_size: int = 200) -> int:
    auto = get_automation(db, FOLLOWUP)
    if not auto.is_enabled or not enabled_channels(auto) or auto.active_since is None:
        return 0
    clinic = get_clinic_settings(db)
    due = _followup_candidates(db, auto, due_before=now - timedelta(minutes=auto.delay_minutes), limit=batch_size)
    count = 0
    messaged = 0
    for customer in due:
        if auto.max_per_run and messaged >= auto.max_per_run:
            break  # the rest wait for the next check
        try:
            sends = process_lead(db, auto, clinic, customer, now)
            count += len(sends)
            messaged += _messaged_anyone(sends)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Lead follow-up failed for customer %s", customer.id)
    return count


# ---------------------------------------------------------------------------
# Re-checks, outcome sync and the outbound queue
# ---------------------------------------------------------------------------


def _set_outbound_status(db: Session, send: AutomationSend, new: str, *, only_from: tuple[str, ...], now: datetime) -> bool:
    """Move the worker's message between states, but only if the worker hasn't claimed it."""
    if not send.outbound_message_id:
        return False
    values = {OutboundMessage.status: new, OutboundMessage.updated_at: now}
    if new == "cancelled":
        values[OutboundMessage.cancelled_at] = now
    changed = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.id == send.outbound_message_id, OutboundMessage.status.in_(only_from))
        .update(values, synchronize_session=False)
    )
    db.expire(send, ["outbound_message"])
    return changed == 1


def _cancel_send(db: Session, send: AutomationSend, reason: str, now: datetime, *, status: str = "cancelled") -> bool:
    """Stop a send that hasn't gone out. False if the worker already has the message."""
    if send.outbound_message_id and not _set_outbound_status(db, send, "cancelled", only_from=("queued", "held"), now=now):
        return False
    send.status, send.reason, send.updated_at = status, reason, now
    return True


def _booking_check(db: Session, send: AutomationSend) -> tuple[str, str | None]:
    """Compare the booking now with the one this message was rendered (and approved) with."""
    appt = db.get(Appointment, send.appointment_id) if send.appointment_id else None
    if not _appointment_is_confirmed(appt):
        return "block", "Booking was cancelled or removed before the message was sent"
    slot, problem = resolve_slot(db, appt)
    if problem:
        return "incomplete", f"Booking details became incomplete: {problem}"
    current = booking_values(slot)
    snapshot = (send.payload or {}).get("booking") or {}
    changes = [
        f"{label}: {snapshot.get(key)} → {current[key]}"
        for key, label in (("event_date", "date"), ("slot", "slot"), ("event_venue", "venue"))
        if snapshot and snapshot.get(key) != current[key]
    ]
    if appt.starts_at != send.slot_starts_at or appt.ends_at != send.slot_ends_at:
        changes = changes or ["the booked time moved"]
    if changes:
        return "changed", "Booking changed after this message was prepared (" + "; ".join(changes) + ")"
    return "ok", None


def recheck(db: Session, send: AutomationSend) -> tuple[str, str | None]:
    """Is this unsent message still right to send?

    ("ok" | "wait" | "block" | "incomplete" | "changed", reason). block: the recipient
    is no longer eligible. wait: a staff message is pending. incomplete / changed: the
    event booking can't be resolved, or differs from what the message was rendered with.
    """
    customer = db.get(Customer, send.customer_id)
    if customer is None:
        return "block", "Patient record was deleted"
    block = channel_block_reason(customer, send.channel) if send.channel else None
    if block:
        return "block", block
    if send.automation_key == CONFIRMATION:
        return _booking_check(db, send)
    return followup_status(db, customer, ignore_outbound_ids=_own_followup_outbound_ids(db, customer.id))


def _apply_problem(db: Session, send: AutomationSend, state: str, reason: str | None, now: datetime) -> bool:
    """Act on a failed re-check of a queued (or paused) message. False if the worker already has it."""
    if state == "block":
        return _cancel_send(db, send, reason, now)
    if state == "wait":
        if send.status == "queued" and not _set_outbound_status(db, send, "held", only_from=("queued", "held"), now=now):
            return False
        send.status, send.reason, send.updated_at = "paused", reason, now
        return True
    # incomplete / changed
    if send.approved_at is not None:
        # Staff approved specific content: never send it once the booking differs, and
        # never replace it automatically. Stop it and ask for a fresh preview + approval.
        return _cancel_send(db, send, f"{reason}. Preview and approve it again.", now, status="reapproval")
    # Sent automatically: drop it; the next check renders a new round from the booking as it is.
    return _cancel_send(db, send, reason, now)


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
    """Copy worker outcomes back, and re-check everything that hasn't gone out yet."""
    changed = 0
    open_sends = (
        db.query(AutomationSend)
        .options(joinedload(AutomationSend.outbound_message))
        .filter(AutomationSend.status.in_(("queued", "paused", "pending_approval", "reapproval", "held")))
        .filter(AutomationSend.channel.isnot(None))
        .all()
    )
    for send in open_sends:
        msg = send.outbound_message
        if send.status == "queued":
            if msg is None:
                send.status, send.reason = "failed", "Queued message was deleted before it was sent"
                _audit_send(db, send, "automation_send.failed")
            elif msg.status == "sent":
                send.status, send.sent_at, send.reason = "sent", msg.updated_at or now, None
                if send.automation_key == CONFIRMATION:
                    _record_confirmation_on_deal(db, send)
                _audit_send(db, send, "automation_send.sent")
            elif msg.status == "failed":
                send.status, send.reason = "failed", msg.last_error or "Provider rejected the message"
                _audit_send(db, send, "automation_send.failed")
            elif msg.status == "cancelled":
                send.status, send.reason = "cancelled", send.reason or "Message was cancelled before sending"
            elif msg.status in ("queued", "held"):  # held = stopped by the worker's send-time check
                state, reason = recheck(db, send)
                if state == "ok":
                    if msg.status != "held" or not _set_outbound_status(db, send, "queued", only_from=("held",), now=now):
                        continue
                    send.reason = None
                elif not _apply_problem(db, send, state, reason, now):
                    continue
                elif send.status in ("reapproval", "cancelled"):
                    _audit_send(db, send, "automation_send.stopped_before_sending")
            else:
                continue  # 'sending': the worker owns it right now
        elif send.status == "paused":
            state, reason = recheck(db, send)
            if state == "ok" and _set_outbound_status(db, send, "queued", only_from=("held",), now=now):
                send.status, send.reason = "queued", None
            elif state not in ("ok", "wait") and _apply_problem(db, send, state, reason, now):
                pass
            else:
                continue
        else:  # pending_approval, reapproval, or held by staff: only an ineligible recipient ends it
            state, reason = recheck(db, send)
            if state != "block" or not _cancel_send(db, send, reason, now):
                continue
        send.updated_at = now
        changed += 1
    db.commit()
    return changed


# ---------------------------------------------------------------------------
# Recipient review: list, preview, include, approve, hold, release, exclude
# ---------------------------------------------------------------------------


class RecipientActionError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Recipient:
    automation_key: str
    customer: Customer
    appointment: Appointment | None
    kind: str
    revision: int
    rows: list[AutomationSend]
    is_new: bool
    prior_sends: list[AutomationSend]


def get_recipient(db: Session, automation_key: str, customer_id, appointment_id=None) -> Recipient:
    """The open round for this recipient, or the one that would be created next."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise RecipientActionError("Patient not found", 404)
    if automation_key == CONFIRMATION:
        appt = db.get(Appointment, appointment_id) if appointment_id else None
        if appt is None or appt.customer_id != customer.id:
            raise RecipientActionError("Event booking not found for this patient", 404)
        rnd = _confirmation_round(db, appt)
        return Recipient(CONFIRMATION, customer, appt, rnd.kind, rnd.revision, rnd.rows, rnd.is_new, rnd.sends)
    if automation_key == FOLLOWUP:
        rows = db.query(AutomationSend).filter(AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == customer.id).all()
        return Recipient(FOLLOWUP, customer, None, "followup", 1, rows, not rows, rows)
    raise RecipientActionError(f"Unknown automation: {automation_key}")


def _recipient_context(db: Session, r: Recipient) -> tuple[dict[str, str] | None, str | None]:
    clinic = get_clinic_settings(db)
    if r.automation_key == CONFIRMATION:
        if not _appointment_is_confirmed(r.appointment):
            return None, f"Booking is {r.appointment.status}, not booked"
        slot, problem = resolve_slot(db, r.appointment)
        if problem:
            return None, problem
        return _confirmation_context(r.customer, clinic, slot), None
    return _patient_context(r.customer, clinic), None


def _slot_summary(db: Session, appt: Appointment | None) -> dict[str, Any] | None:
    if appt is None:
        return None
    slot, problem = resolve_slot(db, appt)
    event = appt.event
    return {
        "event_name": event.name if event else None,
        "event_date": slot.date_text if slot else None,
        "slot": f"{slot.start_text} to {slot.end_text} ({slot.timezone_text})" if slot else None,
        "event_venue": slot.location if slot else ((event.location or None) if event else None),
        "problem": problem,
    }


def _fingerprint(plans: list[ChannelPlan]) -> str:
    """Identifies exactly what staff saw in a preview: approval must match it."""
    items = [
        {"channel": p.channel, "subject": p.rendered.subject, "body": p.rendered.body, "payload": p.rendered.payload()}
        for p in sorted(plans, key=lambda p: p.channel)
    ]
    return hashlib.sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _fresh_plans(db: Session, r: Recipient, channels: Iterable[str] | None = None) -> tuple[list[ChannelPlan], dict[str, str] | None, str | None]:
    """Render now, with the same code as a real send. Writes nothing."""
    context, problem = _recipient_context(db, r)
    if context is None:
        return [], None, problem
    plans = plan_channels(db, get_automation(db, r.automation_key), r.kind, r.customer, context)
    if channels is not None:
        wanted = set(channels)
        plans = [p for p in plans if p.channel in wanted]
    return plans, context, None


AWAITING_APPROVAL_STATUSES = ("pending_approval", "reapproval")


def preview_recipient(db: Session, automation_key: str, customer_id, appointment_id=None) -> dict[str, Any]:
    """Exactly what would be sent. Messages waiting for (re-)approval, and records not yet
    started, are rendered now with the same code as the real send; messages already handed
    to the worker show the content they were queued with. Never writes or sends anything.

    preview_token identifies the rendered content; approving requires it to still match.
    """
    r = get_recipient(db, automation_key, customer_id, appointment_id)
    awaiting = [s for s in r.rows if s.channel and s.status in AWAITING_APPROVAL_STATUSES]
    stored = [s for s in r.rows if s.channel and s.rendered_body and s.status not in AWAITING_APPROVAL_STATUSES]
    channels: list[dict[str, Any]] = []
    problem = None
    token = None
    if awaiting or not stored:
        plans, _context, problem = _fresh_plans(db, r, [s.channel for s in awaiting] if awaiting else None)
        for p in plans:
            channels.append({"channel": p.channel, "address": p.address, "status": p.status, "reason": p.reason,
                             "subject": p.rendered.subject if p.rendered else None,
                             "body": p.rendered.body if p.rendered else None})
        if awaiting and not problem and plans and all(p.status == "ok" for p in plans) and len(plans) == len(awaiting):
            token = _fingerprint(plans)
    else:
        for s in stored:
            channels.append({"channel": s.channel, "address": channel_address(r.customer, s.channel), "status": s.status,
                             "reason": s.reason, "subject": s.rendered_subject, "body": s.rendered_body})
    return {
        "automation_key": automation_key,
        "kind": r.kind,
        "customer_id": str(r.customer.id),
        "customer_name": r.customer.name,
        "appointment_id": str(r.appointment.id) if r.appointment else None,
        "booking": _slot_summary(db, r.appointment),
        "problem": problem,
        "channels": channels,
        "preview_token": token,
    }


def _active_rows(r: Recipient, statuses: tuple[str, ...]) -> list[AutomationSend]:
    return [s for s in r.rows if s.channel and s.status in statuses]


def _prefix(r: Recipient) -> str:
    return f"{r.automation_key}:{r.appointment.id if r.appointment else r.customer.id}"


def _is_existing_record(db: Session, auto: MessagingAutomation, r: Recipient) -> bool:
    """Created or booked before the automation was switched on, and never handled by it."""
    if auto.active_since is None or not r.is_new or r.prior_sends:
        return False
    if r.automation_key == CONFIRMATION:
        appt = r.appointment
        return appt.created_at is not None and appt.created_at < auto.active_since
    return r.customer.created_at < auto.active_since


def include_recipient(db: Session, r: Recipient, user: User, now: datetime) -> list[AutomationSend]:
    """Put an existing record (from before the automation was switched on) up for approval.
    Nothing is sent until a staff member previews and approves it."""
    auto = get_automation(db, r.automation_key)
    if not auto.is_enabled:
        raise RecipientActionError("Switch the automation on first")
    if not _is_existing_record(db, auto, r):
        raise RecipientActionError("Only existing records the automation hasn't handled yet can be included")
    if r.automation_key == CONFIRMATION:
        appt = r.appointment
        if not _appointment_is_confirmed(appt) or appt.starts_at <= _uk_now_as_stored(now):
            raise RecipientActionError("Only upcoming, booked event slots can be confirmed")
        deal = appt.deal
        if deal is not None and deal.confirmation_sent_at is not None and deal.confirmation_sent_at >= appt.created_at:
            raise RecipientActionError("This booking has already been confirmed")
    else:
        state, reason = followup_status(db, r.customer)
        if state == "block":
            raise RecipientActionError(f"Not eligible: {reason}")
        if state == "wait":
            raise RecipientActionError(f"Not yet: {reason}", 409)
    context, problem = _recipient_context(db, r)
    if problem:
        raise RecipientActionError(f"Can't include until this is fixed: {problem}")
    created = _dispatch(db, auto=auto, kind=r.kind, customer=r.customer, dedupe_prefix=_prefix(r), revision=r.revision,
                        appointment=r.appointment, context=context, now=now, force_approval=True)
    pending = [s for s in created if s.status == "pending_approval"]
    if not pending:
        reasons = "; ".join(f"{s.channel}: {s.reason}" for s in created if s.reason) or "no channel can be used"
        raise RecipientActionError(f"Nothing can be sent to this recipient ({reasons})")
    for s in pending:
        _audit_send(db, s, "automation_send.included", actor=user)
    return created


def approve_recipient(db: Session, r: Recipient, user: User, preview_token: str | None, now: datetime) -> int:
    """Send what staff previewed. The message is rendered again now; if it no longer matches
    the preview (booking, template or clinic details changed), approval is refused."""
    entry = _round_entry(r.rows)
    if entry is not None and entry.status == "needs_review":
        raise RecipientActionError(f"Can't approve until this is fixed: {entry.reason}")
    rows = _active_rows(r, AWAITING_APPROVAL_STATUSES)
    if not rows:
        raise RecipientActionError("Nothing is waiting for approval for this recipient")
    for s in rows:
        state, reason = recheck(db, s)
        if state == "block":
            _cancel_send(db, s, reason, now)
            db.commit()
            raise RecipientActionError(f"Can't send: {reason}")
        if state == "wait":
            raise RecipientActionError(f"Not yet: {reason}", 409)
        if state == "incomplete":
            raise RecipientActionError(f"Can't approve until this is fixed: {reason}")
        # "changed" is fine here: the message is re-rendered from the booking as it is now.
    plans, context, problem = _fresh_plans(db, r, [s.channel for s in rows])
    if problem:
        raise RecipientActionError(f"Can't approve until this is fixed: {problem}")
    by_channel = {p.channel: p for p in plans}
    for s in rows:
        p = by_channel.get(s.channel)
        if p is None or p.status != "ok":
            raise RecipientActionError(f"Can't send by {s.channel}: {p.reason if p else 'this channel is switched off'}")
    if not preview_token:
        raise RecipientActionError("Preview the message before approving it")
    if preview_token != _fingerprint(plans):
        raise RecipientActionError(
            "The message has changed since you previewed it (booking, template or clinic details). "
            "Open the preview again and check it before approving.",
            409,
        )
    for s in rows:
        p = by_channel[s.channel]
        s.template_id = p.rendered.template_id
        s.rendered_subject, s.rendered_body = p.rendered.subject, p.rendered.body
        s.payload = _payload_with_booking(p.rendered, context if r.appointment else None)
        if r.appointment is not None:
            s.slot_starts_at, s.slot_ends_at = r.appointment.starts_at, r.appointment.ends_at
        s.approved_at, s.approved_by_user_id, s.reason = now, user.id, None
        _enqueue(db, s, r.customer, now)
        _audit_send(db, s, "automation_send.approved", actor=user)
    return len(rows)


def hold_recipient(db: Session, r: Recipient, user: User, note: str | None, now: datetime) -> None:
    """Pause this recipient's message until a staff member releases it. Temporary: the
    recipient stays in the automation."""
    reason = f"On hold{': ' + note if note else ''}"
    rows = _active_rows(r, ("queued", "paused", "pending_approval", "reapproval"))
    if rows:
        held = []
        for s in rows:
            if s.outbound_message_id and s.status in ("queued", "paused") and not _set_outbound_status(
                db, s, "held", only_from=("queued", "held"), now=now
            ):
                continue  # the worker is already sending this one
            s.payload = {**(s.payload or {}), "held_from": s.status}
            s.status, s.reason, s.updated_at = "held", reason, now
            held.append(s)
            _audit_send(db, s, "automation_send.held", actor=user)
        if not held:
            raise RecipientActionError("Too late: the worker is already sending this message", 409)
        return
    entry = _round_entry(r.rows)
    if any(s.channel for s in r.rows) or (entry is not None and entry.status in ("excluded", "skipped", "resolved", "held")):
        raise RecipientActionError("There's no upcoming message to hold for this recipient")
    if entry is not None:
        entry.status, entry.reason, entry.updated_at = "held", reason, now
    else:
        entry = _add_round_entry(db, auto_key=r.automation_key, kind=r.kind, customer=r.customer, dedupe_prefix=_prefix(r),
                                 revision=r.revision, appointment=r.appointment, status="held", reason=reason, now=now)
    _audit_send(db, entry, "automation_send.held", actor=user)


def release_recipient(db: Session, r: Recipient, user: User, now: datetime) -> None:
    """End a hold. The message carries on from where it was, after re-checking it."""
    rows = _active_rows(r, ("held",))
    if rows:
        for s in rows:
            previous = (s.payload or {}).get("held_from") or ("queued" if s.outbound_message_id else "pending_approval")
            if previous in AWAITING_APPROVAL_STATUSES or not s.outbound_message_id:
                s.status, s.reason, s.updated_at = previous if previous in AWAITING_APPROVAL_STATUSES else "pending_approval", None, now
            else:
                s.status = "queued"
                state, reason = recheck(db, s)
                if state == "ok":
                    if _set_outbound_status(db, s, "queued", only_from=("held",), now=now):
                        s.reason, s.updated_at = None, now
                else:
                    s.status = "paused" if state == "wait" else "queued"
                    _apply_problem(db, s, state, reason, now)
            _audit_send(db, s, "automation_send.released", actor=user)
        return
    entry = _round_entry(r.rows)
    if entry is None or entry.status != "held":
        raise RecipientActionError("This recipient isn't on hold")
    # Picked up by the next automation check, with eligibility re-checked then. A hold
    # never makes the follow-up "too late": releasing it lets it go out.
    entry.status, entry.reason, entry.updated_at = "released", "Released by staff", now
    _audit_send(db, entry, "automation_send.released", actor=user)


def exclude_recipient(db: Session, r: Recipient, user: User, note: str | None, now: datetime) -> None:
    """Remove this recipient from the automation: their message is never sent."""
    reason = f"Excluded by staff{': ' + note if note else ''}"
    rows = _active_rows(r, ("queued", "paused", "pending_approval", "reapproval", "held"))
    if rows:
        done = [s for s in rows if _cancel_send(db, s, reason, now, status="excluded")]
        if not done:
            raise RecipientActionError("Too late: the worker is already sending this message", 409)
        for s in done:
            _audit_send(db, s, "automation_send.excluded", actor=user)
        return
    entry = _round_entry(r.rows)
    if any(s.channel for s in r.rows) or (entry is not None and entry.status in ("excluded", "skipped", "resolved")):
        raise RecipientActionError("This message has already been processed, so there is nothing to exclude")
    if entry is not None:
        entry.status, entry.reason, entry.updated_at = "excluded", reason, now
    else:
        entry = _add_round_entry(db, auto_key=r.automation_key, kind=r.kind, customer=r.customer, dedupe_prefix=_prefix(r),
                                 revision=r.revision, appointment=r.appointment, status="excluded", reason=reason, now=now)
    _audit_send(db, entry, "automation_send.excluded", actor=user)


_OPEN_STATE_ORDER = ("reapproval", "pending_approval", "held", "paused", "queued", "needs_review", "released")
_OPEN_LABEL = {
    "reapproval": "needs_reapproval",
    "pending_approval": "awaiting_approval",
    "held": "held",
    "paused": "waiting",
    "queued": "queued",
    "needs_review": "needs_review",
    "released": "scheduled",
}


def _recipient_entry(db: Session, auto: MessagingAutomation, r: Recipient, *, state: str, planned_at, reason: str | None) -> dict[str, Any]:
    if r.rows and any(s.channel for s in r.rows):
        channels = [{"channel": s.channel, "address": channel_address(r.customer, s.channel), "status": s.status, "reason": s.reason}
                    for s in r.rows if s.channel]
    else:
        plans, _context, problem = _fresh_plans(db, r)
        channels = [{"channel": p.channel, "address": p.address, "status": p.status, "reason": p.reason} for p in plans]
        if problem and state in ("scheduled", "existing"):
            reason = problem
            if state == "scheduled":
                state = "needs_review"
    sendable = any(c["status"] in ("ok", "pending_approval", "reapproval", "queued", "paused", "held") for c in channels)
    return {
        "automation_key": r.automation_key,
        "kind": r.kind,
        "customer_id": str(r.customer.id),
        "customer_name": r.customer.name,
        "appointment_id": str(r.appointment.id) if r.appointment else None,
        "booking": _slot_summary(db, r.appointment),
        "state": state,
        "reason": reason,
        "planned_at": planned_at.isoformat() if planned_at else None,
        "requires_approval": auto.require_approval or state == "existing",
        "automation_enabled": auto.is_enabled,
        "channels": channels,
        "can_include": state == "existing" and sendable and not reason,
        "can_approve": state in ("awaiting_approval", "needs_reapproval"),
        "can_hold": state in ("scheduled", "awaiting_approval", "needs_reapproval", "queued", "waiting") and sendable,
        "can_release": state == "held",
        "can_exclude": state in ("scheduled", "existing", "awaiting_approval", "needs_reapproval", "queued", "waiting", "held", "needs_review"),
    }


def list_recipients(db: Session, now: datetime | None = None, *, limit: int = 300) -> list[dict[str, Any]]:
    """Who is due to receive an automated message, soonest first, then existing records
    staff may choose to include. Writes nothing."""
    now = now or _now()
    out: list[dict[str, Any]] = []
    existing: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    autos = {k: get_automation(db, k) for k in AUTOMATION_KEYS}

    # Rounds in progress: awaiting (re-)approval, on hold, waiting on a staff message, queued, held for review.
    open_rows = (
        db.query(AutomationSend)
        .filter(AutomationSend.status.in_(_OPEN_STATE_ORDER))
        .order_by(AutomationSend.created_at.asc())
        .all()
    )
    for s in open_rows:
        key = (s.automation_key, s.customer_id, s.appointment_id)
        if key in seen:
            continue
        try:
            r = get_recipient(db, s.automation_key, s.customer_id, s.appointment_id)
        except RecipientActionError:
            continue
        if r.revision != s.revision:
            continue  # stale row from an older round
        seen.add(key)
        statuses = [x.status for x in r.rows]
        raw = next((st for st in _OPEN_STATE_ORDER if st in statuses), "released")
        state = _OPEN_LABEL[raw]
        reason = next((x.reason for x in r.rows if x.status == raw and x.reason), None)
        planned = now if state in ("scheduled", "queued") else None
        out.append(_recipient_entry(db, autos[s.automation_key], r, state=state, planned_at=planned, reason=reason))

    # Event bookings: the next check confirms new ones; earlier ones are listed as existing records.
    conf = autos[CONFIRMATION]
    if conf.is_enabled and conf.active_since is not None:
        for appt in _upcoming_confirmed_appointments(db, now):
            key = (CONFIRMATION, appt.customer_id, appt.id)
            if key in seen:
                continue
            r = get_recipient(db, CONFIRMATION, appt.customer_id, appt.id)
            if not r.is_new or (r.kind == "update" and not conf.send_updates):
                continue
            deal = appt.deal
            if not r.prior_sends and deal is not None and deal.confirmation_sent_at is not None and deal.confirmation_sent_at >= appt.created_at:
                continue  # staff already confirmed it
            seen.add(key)
            if _is_existing_record(db, conf, r):
                existing.append(_recipient_entry(db, conf, r, state="existing", planned_at=None, reason=None))
            else:
                out.append(_recipient_entry(db, conf, r, state="scheduled", planned_at=now, reason=None))

    # Leads: follow-ups coming up, then eligible leads from before the automation was switched on.
    fol = autos[FOLLOWUP]
    if fol.is_enabled and fol.active_since is not None:
        delay = timedelta(minutes=fol.delay_minutes)
        undecided = sa.exists().where(AutomationSend.automation_key == FOLLOWUP, AutomationSend.customer_id == Customer.id,
                                      AutomationSend.status != "released")
        leads = (
            db.query(Customer).filter(~undecided).order_by(Customer.created_at.desc()).limit(limit).all()
        )
        for customer in leads:
            key = (FOLLOWUP, customer.id, None)
            if key in seen:
                continue
            state, reason = followup_status(db, customer)
            if state == "block":
                continue  # won't receive anything
            r = get_recipient(db, FOLLOWUP, customer.id)
            seen.add(key)
            if _is_existing_record(db, fol, r):
                if state == "ok":
                    existing.append(_recipient_entry(db, fol, r, state="existing", planned_at=None, reason=None))
                continue
            due_at = customer.created_at + delay
            if now - due_at > FOLLOWUP_MAX_LATENESS:
                continue
            out.append(_recipient_entry(db, fol, r, state="waiting" if state == "wait" else "scheduled",
                                        planned_at=max(due_at, now), reason=reason))

    out.sort(key=lambda e: (e["planned_at"] is None, e["planned_at"] or ""))
    return (out + existing)[:limit]


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
