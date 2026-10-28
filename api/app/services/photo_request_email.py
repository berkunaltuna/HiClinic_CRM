"""Email a patient their photo-upload link through the existing outbox.

- One email per portal link (photo_request_emails.link_id is unique), and a request whose
  current link already has a queued/sending/sent email is returned as-is, so retries never
  send a second email.
- The raw link exists only in the outbound message until the worker sends it; the worker
  keeps it out of the contact thread and wipes it from the message afterwards (see
  `_redact` in worker/app/worker.py), and the outbox API masks it.
- Everything happens in one savepoint: if the patient has no usable email, has opted out,
  or the message cannot be queued, nothing is recorded as sent and the pipeline is untouched.
"""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    Customer,
    Deal,
    DealStatus,
    OutboundMessage,
    PhotoAccessLink,
    PhotoRequest,
    PhotoRequestEmail,
    Template,
    User,
)
from app.services.audit import record_audit
from app.services.photo_portal_auth import UPLOADABLE_STATUSES, link_is_usable

TEMPLATE_NAME = "photo_request_link"
TEMPLATE_SUBJECT = "Your secure photo upload link"
# Mirrors migration 0025 (used when the template row is missing, e.g. in tests).
TEMPLATE_BODY = (
    "Hi {{first_name}},\n\n"
    "The clinic has asked you to share some photos. Please use your personal, secure link to upload them:\n\n"
    "{{portal_link}}\n\n"
    "The link expires on {{link_expires}}. Please do not forward it to anyone.\n\n"
    "Please don't reply to this email with photos. Only upload them through the link above.\n\n"
    "If you weren't expecting this message, please contact the clinic."
)
# Sent when staff edit a request's details; carries a fresh link and leaves earlier links working.
UPDATED_TEMPLATE_NAME = "photo_request_updated"
UPDATED_TEMPLATE_SUBJECT = "Your photo request has been updated"
UPDATED_TEMPLATE_BODY = (
    "Hi {{first_name}},\n\n"
    "The clinic has updated its request for photos. Please open your personal, secure link to see what is needed now:\n\n"
    "{{portal_link}}\n\n"
    "The link expires on {{link_expires}}. Any link we sent you earlier for this request still works too. "
    "Please do not forward it to anyone.\n\n"
    "Please don't reply to this email with photos. Only upload them through the link above.\n\n"
    "If you weren't expecting this message, please contact the clinic."
)
LINK_PLACEHOLDER = "{{portal_link}}"
# Outbox statuses that mean "this email is on its way or delivered".
LIVE_STATUSES = ("queued", "sending", "sent")

# Pipeline order for forward-only moves. "lost" and unknown/legacy stages are never moved.
PIPELINE_ORDER = [
    "new",
    "contacted",
    "waiting_for_response",
    "interested",
    "photos_requested",
    "appointment_booked",
    "pro_forma_sent",
    "waiting_on_dates",
    "deposit_requested",
    "deposit_paid",
    "treatment_completed",
]
PHOTOS_REQUESTED = "photos_requested"


class DealSelectionRequired(HTTPException):
    def __init__(self, deals: list[Deal]):
        super().__init__(
            status_code=409,
            detail={
                "code": "deal_selection_required",
                "message": "This patient has more than one open enquiry. Choose which one these photos are for.",
                "deals": [
                    {"id": str(d.id), "label": f"{d.treatment_interest or 'Enquiry'} ({d.status.value if hasattr(d.status, 'value') else d.status})"}
                    for d in deals
                ],
            },
        )


def valid_patient_email(customer: Customer) -> str:
    raw = (customer.email or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="This patient has no email address. Add one to the contact, or copy the link and send it another way.")
    try:
        return validate_email(raw, check_deliverability=False).normalized
    except EmailNotValidError:
        raise HTTPException(status_code=422, detail=f"The patient's email address ({raw}) is not valid. Correct it on the contact first.")


def email_template(db: Session, *, updated: bool = False) -> Template:
    """The link email template (or, with updated=True, the "request updated" one)."""
    name, subject, body = (
        (UPDATED_TEMPLATE_NAME, UPDATED_TEMPLATE_SUBJECT, UPDATED_TEMPLATE_BODY) if updated else (TEMPLATE_NAME, TEMPLATE_SUBJECT, TEMPLATE_BODY)
    )
    tpl = db.query(Template).filter(Template.channel == "email", Template.name == name, Template.language == "und").first()
    if tpl is None:
        tpl = Template(channel="email", name=name, subject=subject, body=body, category="transactional", language="und")
        db.add(tpl)
        db.flush()
    if LINK_PLACEHOLDER not in (tpl.body or ""):
        raise HTTPException(
            status_code=503,
            detail=f"The '{name}' email template no longer contains {LINK_PLACEHOLDER}. Fix it on the Templates page.",
        )
    return tpl


def queue_outbound_email(db: Session, *, customer: Customer, sender: User, template: Template, variables: dict) -> OutboundMessage:
    """Put the email on the existing outbox queue (the worker sends it)."""
    msg = OutboundMessage(
        owner_user_id=sender.id,
        customer_id=customer.id,
        channel="email",
        status="queued",
        template_id=template.id,
        variables=variables,
    )
    db.add(msg)
    db.flush()
    return msg


def resolve_deal(db: Session, req: PhotoRequest, deal_id) -> Deal | None:
    """The enquiry this request belongs to: the one given, the one already linked, or the
    patient's only open enquiry. Several open enquiries and no choice -> ask staff."""
    if deal_id is not None:
        deal = db.get(Deal, deal_id)
        if deal is None or deal.customer_id != req.customer_id:
            raise HTTPException(status_code=422, detail="That enquiry does not belong to this patient")
        return deal
    if req.deal_id is not None:
        return db.get(Deal, req.deal_id)
    open_deals = db.query(Deal).filter(Deal.customer_id == req.customer_id, Deal.status == DealStatus.open).order_by(Deal.created_at.desc()).all()
    if len(open_deals) > 1:
        raise DealSelectionRequired(open_deals)
    return open_deals[0] if open_deals else None


def advance_pipeline(db: Session, customer: Customer, actor: User, request_id) -> dict:
    """Move this patient's pipeline card to Photos Requested, forward only."""
    current = customer.stage or "new"
    if current not in PIPELINE_ORDER:
        return {"changed": False, "stage": current, "reason": "stage is not before Photos Requested"}
    if PIPELINE_ORDER.index(current) >= PIPELINE_ORDER.index(PHOTOS_REQUESTED):
        return {"changed": False, "stage": current, "reason": "already at or past Photos Requested"}
    customer.stage = PHOTOS_REQUESTED
    record_audit(
        db,
        actor=actor,
        action="pipeline.stage_changed",
        entity_type="customer",
        entity_id=customer.id,
        before={"stage": current},
        after={"stage": PHOTOS_REQUESTED},
        metadata={"source": "photo_request_email", "photo_request_id": str(request_id)},
    )
    return {"changed": True, "from": current, "stage": PHOTOS_REQUESTED}


def existing_live_email(db: Session, req: PhotoRequest) -> PhotoRequestEmail | None:
    """An email already on its way for the request's current, usable link."""
    rows = (
        db.query(PhotoRequestEmail)
        .join(PhotoAccessLink, PhotoAccessLink.id == PhotoRequestEmail.link_id)
        .filter(PhotoRequestEmail.request_id == req.id, PhotoAccessLink.revoked_at.is_(None))
        .order_by(PhotoRequestEmail.created_at.desc())
        .all()
    )
    for row in rows:
        link = db.get(PhotoAccessLink, row.link_id)
        msg = row.outbound_message
        if link is not None and link_is_usable(link) and msg is not None and msg.status in LIVE_STATUSES:
            return row
    return None


def check_can_email(req: PhotoRequest) -> str:
    if req.status not in UPLOADABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Photos can only be requested while the request is open for uploads")
    customer = req.customer
    to = valid_patient_email(customer)
    if customer.can_contact is False:
        raise HTTPException(status_code=422, detail="This patient has opted out of contact, so the link cannot be emailed.")
    return to
