from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.auth.deps import get_current_user, require_admin
from app.core.config import settings
from app.db.models import AutomationSend, Customer, MessagingAutomation, Template, User
from app.db.session import get_db
from app.schemas.messaging_automation import (
    AutomationKey,
    AutomationSendOut,
    AutomationsOverview,
    ClinicSettingsOut,
    ClinicSettingsUpdate,
    MessagingAutomationOut,
    MessagingAutomationUpdate,
)
from app.services import messaging_automations as ma
from app.services.audit import record_audit

router = APIRouter(prefix="/automations", tags=["automations"])

_TEMPLATE_FIELDS = {
    "email_template_id": "email",
    "whatsapp_template_id": "whatsapp",
    "update_email_template_id": "email",
    "update_whatsapp_template_id": "whatsapp",
}
_REQUIRED_CONFIRMATION_FIELDS = ("appointment_date", "appointment_time", "appointment_timezone", "appointment_location")


def _template_warnings(db: Session, auto: MessagingAutomation, clinic) -> list[str]:
    warnings: list[str] = []
    if auto.is_enabled and not ma.enabled_channels(auto):
        warnings.append("Automation is on but no channel is selected, so nothing will be sent.")
    slots = [("", "email_template_id", "whatsapp_template_id")]
    if auto.key == ma.CONFIRMATION and auto.send_updates:
        slots.append(("Rescheduled ", "update_email_template_id", "update_whatsapp_template_id"))
    for prefix, email_attr, wa_attr in slots:
        for channel, attr in (("email", email_attr), ("whatsapp", wa_attr)):
            if not getattr(auto, f"{channel}_enabled"):
                continue
            label = f"{prefix}{'email' if channel == 'email' else 'WhatsApp'} template"
            tpl = db.get(Template, getattr(auto, attr)) if getattr(auto, attr) else None
            if tpl is None:
                warnings.append(f"{label}: none selected.")
                continue
            tokens = ma.template_tokens(tpl.subject if channel == "email" else None, tpl.body)
            unsupported = [t for t in tokens if t not in ma.SUPPORTED_FIELDS[auto.key]]
            if unsupported:
                warnings.append(f"{label} '{tpl.name}' uses unsupported field(s): {', '.join(unsupported)}.")
            if auto.key == ma.CONFIRMATION:
                missing = [f for f in _REQUIRED_CONFIRMATION_FIELDS if f not in tokens]
                if missing:
                    warnings.append(f"{label} '{tpl.name}' doesn't include: {', '.join(missing)}.")
                if not ({"clinic_phone", "clinic_email"} & set(tokens)) and not tpl.provider_template_id:
                    warnings.append(f"{label} '{tpl.name}' doesn't include a way to contact the clinic.")
            for field, value in (("clinic_phone", clinic.contact_phone), ("clinic_email", clinic.contact_email)):
                if field in tokens and not (value or "").strip():
                    warnings.append(f"{label} '{tpl.name}' uses {{{{{field}}}}} but the clinic {field.split('_')[1]} isn't set, so sends will be held for review.")
            if channel == "whatsapp" and not tpl.provider_template_id:
                warnings.append(
                    f"{label} '{tpl.name}' has no Twilio Content SID. WhatsApp only accepts free-form messages within "
                    "24 hours of the patient's last message, so most sends will be held for review until an approved "
                    "template's SID is added."
                )
    return warnings


def _global_warnings(db: Session) -> list[str]:
    warnings: list[str] = []
    if not settings.automations_scheduler_enabled:
        warnings.append("The automation scheduler is switched off on this server (AUTOMATIONS_SCHEDULER_ENABLED=false).")
    if settings.email_provider != "smtp":
        warnings.append(f"EMAIL_PROVIDER is '{settings.email_provider}', so emails are not really delivered.")
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from):
        warnings.append("Twilio WhatsApp credentials (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM) are not set, so WhatsApp sends will fail.")
    for channel, column in (("email", Customer.email_consent), ("WhatsApp", Customer.whatsapp_consent)):
        if db.query(Customer.id).filter(column.is_(True)).first() is None:
            warnings.append(f"No patient has {channel} consent recorded yet. Nothing is sent on {channel} until consent is recorded on the contact page.")
    return warnings


def _automation_out(db: Session, auto: MessagingAutomation, clinic) -> MessagingAutomationOut:
    out = MessagingAutomationOut.model_validate(auto)
    out.supported_fields = ma.SUPPORTED_FIELDS[auto.key]
    out.warnings = _template_warnings(db, auto, clinic)
    return out


def _overview(db: Session) -> AutomationsOverview:
    clinic = ma.get_clinic_settings(db)
    autos = [ma.get_automation(db, key) for key in ma.AUTOMATION_KEYS]
    db.commit()
    return AutomationsOverview(
        clinic=ClinicSettingsOut.model_validate(clinic),
        automations=[_automation_out(db, a, clinic) for a in autos],
        warnings=_global_warnings(db),
    )


def _snapshot(auto: MessagingAutomation) -> dict:
    return {
        "is_enabled": auto.is_enabled,
        "email_enabled": auto.email_enabled,
        "whatsapp_enabled": auto.whatsapp_enabled,
        "send_updates": auto.send_updates,
        "delay_minutes": auto.delay_minutes,
        "max_per_run": auto.max_per_run,
        **{k: str(getattr(auto, k)) if getattr(auto, k) else None for k in _TEMPLATE_FIELDS},
    }


@router.get("", response_model=AutomationsOverview)
def get_automations(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AutomationsOverview:
    return _overview(db)


@router.put("/clinic", response_model=AutomationsOverview)
def update_clinic(payload: ClinicSettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> AutomationsOverview:
    clinic = ma.get_clinic_settings(db)
    before = {"clinic_name": clinic.clinic_name, "contact_phone": clinic.contact_phone, "contact_email": clinic.contact_email}
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        if key == "clinic_name" and not value:
            raise HTTPException(status_code=400, detail="Clinic name is required")
        setattr(clinic, key, str(value) if value is not None else None)
    clinic.updated_at = datetime.now(timezone.utc)
    record_audit(db, actor=admin, action="clinic_settings.updated", entity_type="clinic_settings", before=before,
                 after={"clinic_name": clinic.clinic_name, "contact_phone": clinic.contact_phone, "contact_email": clinic.contact_email})
    db.commit()
    return _overview(db)


@router.patch("/{key}", response_model=AutomationsOverview)
def update_automation(key: AutomationKey, payload: MessagingAutomationUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> AutomationsOverview:
    auto = ma.get_automation(db, key)
    before = _snapshot(auto)
    data = payload.model_dump(exclude_unset=True)

    for field in ("is_enabled", "email_enabled", "whatsapp_enabled", "send_updates", "delay_minutes"):
        if field in data and data[field] is None:
            raise HTTPException(status_code=400, detail=f"{field} cannot be null")
    if "delay_minutes" in data and not ma.MIN_FOLLOWUP_DELAY_MINUTES <= data["delay_minutes"] <= ma.MAX_FOLLOWUP_DELAY_MINUTES:
        raise HTTPException(status_code=400, detail=f"Delay must be between {ma.MIN_FOLLOWUP_DELAY_MINUTES} minutes and 30 days")
    for field, channel in _TEMPLATE_FIELDS.items():
        if data.get(field) is None:
            continue
        tpl = db.get(Template, data[field])
        if tpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        if tpl.channel != channel:
            raise HTTPException(status_code=400, detail=f"Template '{tpl.name}' is not a {channel} template")

    was_enabled = auto.is_enabled
    for field, value in data.items():
        setattr(auto, field, value)
    now = datetime.now(timezone.utc)
    if auto.is_enabled and not was_enabled:
        # Only bookings/leads created from now on are handled; nothing is back-filled.
        auto.active_since = now
    auto.updated_at = now
    auto.updated_by_user_id = admin.id
    record_audit(db, actor=admin, action="automation.updated", entity_type="automation", before=before, after=_snapshot(auto), metadata={"automation": key})
    db.commit()
    return _overview(db)


@router.get("/sends", response_model=list[AutomationSendOut])
def list_sends(
    automation_key: AutomationKey | None = None,
    status: str | None = None,
    attention: bool = False,
    customer_id: UUID | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AutomationSendOut]:
    q = db.query(AutomationSend).options(joinedload(AutomationSend.customer))
    if automation_key:
        q = q.filter(AutomationSend.automation_key == automation_key)
    if status:
        q = q.filter(AutomationSend.status == status)
    if attention:
        # Failures and held-back sends, plus confirmations that reached the patient on no
        # channel at all. A skipped channel is fine when another channel delivered.
        sibling = aliased(AutomationSend)
        delivered_elsewhere = (
            exists()
            .where(sibling.automation_key == ma.CONFIRMATION)
            .where(sibling.appointment_id == AutomationSend.appointment_id)
            .where(sibling.revision == AutomationSend.revision)
            .where(sibling.status.in_(("queued", "sent")))
        )
        q = q.filter(
            or_(
                AutomationSend.status.in_(ma.ATTENTION_STATUSES),
                (AutomationSend.automation_key == ma.CONFIRMATION) & (AutomationSend.status == "skipped") & ~delivered_elsewhere,
            )
        )
    if customer_id:
        q = q.filter(AutomationSend.customer_id == customer_id)
    if not settings.share_customers_across_users:
        q = q.join(Customer, Customer.id == AutomationSend.customer_id).filter(Customer.owner_user_id == user.id)
    return q.order_by(AutomationSend.created_at.desc()).limit(max(1, min(limit, 500))).all()


@router.post("/sends/{send_id}/dismiss", response_model=AutomationSendOut)
def dismiss_send(send_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AutomationSendOut:
    send = db.get(AutomationSend, send_id)
    if send is None:
        raise HTTPException(status_code=404, detail="Automation send not found")
    if send.status not in ("failed", "needs_review", "skipped"):
        raise HTTPException(status_code=400, detail=f"A '{send.status}' send can't be dismissed")
    before = {"status": send.status}
    send.status = "dismissed"
    send.updated_at = datetime.now(timezone.utc)
    record_audit(db, actor=user, action="automation_send.dismissed", entity_type="customer", entity_id=send.customer_id,
                 before=before, after={"status": send.status, "reason": send.reason},
                 metadata={"customer_id": str(send.customer_id), "automation_send_id": str(send.id)})
    db.commit()
    db.refresh(send)
    return send


@router.post("/run")
def run_now(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    return ma.run_tick(db)
