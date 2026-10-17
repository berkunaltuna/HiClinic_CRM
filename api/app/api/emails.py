from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.models import Customer, Deal, Interaction, Template, User
from app.db.session import get_db
from app.schemas.email import ConfirmationEmailRequest, EmailSendOut, EmailSendRequest, TemplatePreviewOut
from app.services.audit import record_audit
from app.services.email_provider import get_email_provider
from app.services.message_format import looks_like_html, text_to_html
from app.services import messaging_automations as ma
from app.services.template_render import render_template

router = APIRouter(prefix="/customers", tags=["email"])


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not settings.share_customers_across_users and customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _select_template(db: Session, *, template_id: UUID | None, template_name: str | None, customer: Customer, channel: str = "email") -> Template:
    if template_id is not None:
        tpl = db.get(Template, template_id)
        if tpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return tpl

    assert template_name is not None
    preferred_lang = (customer.language or "und").strip().lower() if customer.language else "und"

    tpl = db.query(Template).filter(Template.channel == channel, Template.name == template_name, Template.language == preferred_lang).first()
    if tpl:
        return tpl

    tpl = db.query(Template).filter(Template.channel == channel, Template.name == template_name, Template.language == "und").first()
    if tpl:
        return tpl

    raise HTTPException(status_code=404, detail="Template not found")


def _get_email_provider():
    return get_email_provider(
        provider=settings.email_provider,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_password=settings.smtp_password,
        smtp_from_email=settings.smtp_from_email,
        smtp_from_name=settings.smtp_from_name,
        smtp_use_starttls=settings.smtp_use_starttls,
    )


def _latest_deal(customer: Customer) -> Deal | None:
    return customer.latest_deal


def _context_for_customer(db: Session, customer: Customer, appointment_id: UUID | None = None) -> tuple[dict[str, str], str | None]:
    """Merge-field values for a manual send, plus why booking fields couldn't resolve (if so).

    Booking fields (event date, slot, venue, ...) come only from the person's own
    active event booking in the Events tab, never from an event they're merely
    linked to on a deal. When there's no usable booking they stay empty and the
    reason is returned so the send can be refused instead of going out blank.
    """
    deal = _latest_deal(customer)
    appt, slot, booking_problem = ma.resolve_customer_booking(db, customer, appointment_id=appointment_id)
    event = appt.event if appt is not None else None
    doctor_name = ""
    if event and event.description:
        # Optional simple convention: put Doctor: Prof. X in the event description.
        for line in event.description.splitlines():
            if line.lower().startswith("doctor:"):
                doctor_name = line.split(":", 1)[1].strip()
                break
    clinic = ma.get_clinic_settings(db)
    name = (customer.name or "").strip()
    context = {
        "customer_name": name,
        "first_name": name.split()[0] if name else "",
        "name": name,
        "clinic_name": clinic.clinic_name or "Health Clinic",
        "clinic_phone": clinic.contact_phone or "",
        "clinic_email": clinic.contact_email or "",
        "company": customer.company or "",
        "customer_email": customer.email or "",
        "customer_phone": customer.phone or "",
        "doctor_name": doctor_name,
        "treatment_interest": deal.treatment_interest if deal and deal.treatment_interest else "",
        "preferred_consultation_day": deal.preferred_consultation_day if deal and deal.preferred_consultation_day else "",
        "seminar_preference": deal.seminar_preference if deal and deal.seminar_preference else "",
    }
    booking_keys = ma.BOOKING_FIELDS + ma.LEGACY_BOOKING_FIELDS
    values = ma.booking_values(slot) if slot is not None else {}
    context.update({k: values.get(k, "") for k in booking_keys})
    return context, booking_problem


def _check_fields(context: dict[str, str], booking_problem: str | None, *texts: str | None) -> None:
    """Refuse to send a message that would go out with blank or unknown fields."""
    tokens = ma.template_tokens(*texts)
    unknown = [t for t in tokens if t not in context]
    if unknown:
        raise HTTPException(status_code=400, detail=f"The message uses unknown field(s): {', '.join('{{' + t + '}}' for t in unknown)}")
    booking_used = [t for t in tokens if t in ma.BOOKING_FIELDS or t in ma.LEGACY_BOOKING_FIELDS]
    if booking_used and booking_problem:
        raise HTTPException(
            status_code=400,
            detail=f"Can't fill in the booking details: {booking_problem}. Book them into an event slot (or fix the event) "
            f"in the Events tab, or remove {', '.join('{{' + t + '}}' for t in booking_used)} from the message.",
        )


def _send_rendered_email(db: Session, user: User, customer: Customer, subject: str, body: str, *, source: str | None = None) -> tuple[str, Interaction]:
    """Send an email. Plain-text bodies (judged on the unrendered source) are formatted
    as HTML for the inbox; the CRM thread keeps the readable text."""
    if not customer.can_contact:
        raise HTTPException(status_code=403, detail="Customer cannot be contacted")
    if not customer.email:
        raise HTTPException(status_code=400, detail="Customer email is missing")
    if not subject.strip() or not body.strip():
        raise HTTPException(status_code=400, detail="subject and body are required")

    html_body = body if looks_like_html(source if source is not None else body) else text_to_html(body)
    provider = _get_email_provider()
    provider_message_id = provider.send_email(to_email=customer.email, subject=subject, body=html_body)
    interaction = Interaction(
        customer_id=customer.id,
        owner_user_id=user.id,
        channel="email",
        direction="outbound",
        occurred_at=datetime.now(tz=timezone.utc),
        content=body,
        subject=subject,
        provider_message_id=provider_message_id,
    )
    db.add(interaction)
    return provider_message_id, interaction


@router.post("/{customer_id}/email/send", response_model=EmailSendOut, status_code=status.HTTP_201_CREATED)
def send_email(
    customer_id: UUID,
    payload: EmailSendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EmailSendOut:
    customer = _get_customer(db, customer_id, user)
    context, booking_problem = _context_for_customer(db, customer)

    if payload.template_id is not None or payload.template_name is not None:
        tpl = _select_template(db, template_id=payload.template_id, template_name=payload.template_name, customer=customer)
        if tpl.category == "marketing" and not customer.can_contact:
            raise HTTPException(status_code=403, detail="Customer cannot be contacted for marketing")
        _check_fields(context, booking_problem, tpl.subject, tpl.body)
        rendered = render_template(subject=tpl.subject, body=tpl.body, context=context)
        rendered_subject, rendered_body = rendered.subject or "", rendered.body
        source = tpl.body
    else:
        _check_fields(context, booking_problem, payload.subject, payload.body)
        rendered = render_template(subject=payload.subject or "", body=payload.body or "", context=context)
        rendered_subject, rendered_body = rendered.subject or "", rendered.body
        source = payload.body or ""

    provider_message_id, interaction = _send_rendered_email(db, user, customer, rendered_subject, rendered_body, source=source)
    record_audit(db, actor=user, action="email.sent", entity_type="customer", entity_id=customer.id, after={"subject": rendered_subject}, metadata={"customer_id": str(customer.id), "customer_name": customer.name})
    db.commit()
    db.refresh(interaction)
    return EmailSendOut(provider_message_id=provider_message_id, interaction_id=interaction.id)


@router.post("/{customer_id}/email/confirmation/preview", response_model=TemplatePreviewOut)
def preview_confirmation_email(
    customer_id: UUID,
    payload: ConfirmationEmailRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplatePreviewOut:
    customer = _get_customer(db, customer_id, user)
    context, booking_problem = _context_for_customer(db, customer, payload.appointment_id)
    if payload.template_id is not None or payload.template_name is not None:
        tpl = _select_template(db, template_id=payload.template_id, template_name=payload.template_name, customer=customer)
        _check_fields(context, booking_problem, tpl.subject, tpl.body)
        rendered = render_template(subject=tpl.subject, body=tpl.body, context=context)
    else:
        _check_fields(context, booking_problem, payload.subject, payload.body)
        rendered = render_template(subject=payload.subject or "", body=payload.body or "", context=context)
    return TemplatePreviewOut(subject=rendered.subject, body=rendered.body)


@router.post("/{customer_id}/email/confirmation/send", response_model=EmailSendOut, status_code=status.HTTP_201_CREATED)
def send_confirmation_email(
    customer_id: UUID,
    payload: ConfirmationEmailRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EmailSendOut:
    customer = _get_customer(db, customer_id, user)
    context, booking_problem = _context_for_customer(db, customer, payload.appointment_id)
    template_id = payload.template_id
    if payload.template_id is not None or payload.template_name is not None:
        tpl = _select_template(db, template_id=payload.template_id, template_name=payload.template_name, customer=customer)
        template_id = tpl.id
        _check_fields(context, booking_problem, tpl.subject, tpl.body)
        rendered = render_template(subject=tpl.subject, body=tpl.body, context=context)
        subject, body = rendered.subject or "", rendered.body
        source = tpl.body
    else:
        _check_fields(context, booking_problem, payload.subject, payload.body)
        rendered = render_template(subject=payload.subject or "", body=payload.body or "", context=context)
        subject, body = rendered.subject or "", rendered.body
        source = payload.body or ""

    provider_message_id, interaction = _send_rendered_email(db, user, customer, subject, body, source=source)
    deal = _latest_deal(customer)
    if deal is not None:
        deal.confirmation_sent_at = datetime.now(timezone.utc)
        deal.confirmation_channel = "email"
        deal.confirmation_template_id = template_id
        deal.confirmed_by_user_id = user.id
    record_audit(db, actor=user, action="appointment.confirmation_sent", entity_type="customer", entity_id=customer.id, after={"channel": "email", "subject": subject}, metadata={"customer_id": str(customer.id), "customer_name": customer.name})
    db.commit()
    db.refresh(interaction)
    return EmailSendOut(provider_message_id=provider_message_id, interaction_id=interaction.id)


@router.get("/{customer_id}/message-fields")
def message_fields(
    customer_id: UUID,
    appointment_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Merge-field values for this person, for messages composed in the browser (WhatsApp quick message)."""
    customer = _get_customer(db, customer_id, user)
    context, booking_problem = _context_for_customer(db, customer, appointment_id)
    return {
        "values": context,
        "booking_problem": booking_problem,
        "booking_fields": ma.BOOKING_FIELDS + ma.LEGACY_BOOKING_FIELDS,
    }
