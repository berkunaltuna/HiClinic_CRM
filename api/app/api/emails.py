from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.models import Customer, Interaction, Template, User
from app.db.session import get_db
from app.schemas.email import EmailSendOut, EmailSendRequest
from app.services.email_provider import FakeEmailProvider
from app.services.template_render import render_template


router = APIRouter(prefix="/customers", tags=["email"])


def _get_owned_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _select_template(
    db: Session, *, template_id: UUID | None, template_name: str | None, customer: Customer
) -> Template:
    if template_id is not None:
        tpl = db.get(Template, template_id)
        if tpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return tpl

    # name-based selection with language preference
    assert template_name is not None
    preferred_lang = (customer.language or "und").strip().lower() if customer.language else "und"

    tpl = (
        db.query(Template)
        .filter(Template.channel == "email", Template.name == template_name, Template.language == preferred_lang)
        .first()
    )
    if tpl:
        return tpl

    # fallback to default language
    tpl = (
        db.query(Template)
        .filter(Template.channel == "email", Template.name == template_name, Template.language == "und")
        .first()
    )
    if tpl:
        return tpl

    raise HTTPException(status_code=404, detail="Template not found")


def _get_email_provider():
    # Phase 3: fake provider only
    if settings.email_provider != "fake":
        # Not implemented yet; keep future-proof error.
        raise RuntimeError("Only EMAIL_PROVIDER=fake is supported in this phase")
    return FakeEmailProvider()


@router.post("/{customer_id}/email/send", response_model=EmailSendOut, status_code=status.HTTP_201_CREATED)
def send_email(
    customer_id: UUID,
    payload: EmailSendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EmailSendOut:
    customer = _get_owned_customer(db, customer_id, user)

    if not customer.can_contact:
        raise HTTPException(status_code=403, detail="Customer cannot be contacted")

    if not customer.email:
        raise HTTPException(status_code=400, detail="Customer email is missing")

    tpl = _select_template(
        db, template_id=payload.template_id, template_name=payload.template_name, customer=customer
    )

    # Basic categorisation enforcement (same boolean for now; future can be granular)
    if tpl.category == "marketing" and not customer.can_contact:
        raise HTTPException(status_code=403, detail="Customer cannot be contacted for marketing")

    context = {
        "customer_name": customer.name,
        "company": customer.company,
    }
    rendered = render_template(subject=tpl.subject, body=tpl.body, context=context)
    if not rendered.subject:
        raise HTTPException(status_code=400, detail="Rendered subject is empty")

    provider = _get_email_provider()
    provider_message_id = provider.send_email(
        to_email=customer.email, subject=rendered.subject, body=rendered.body
    )

    interaction = Interaction(
        customer_id=customer.id,
        owner_user_id=user.id,
        channel="email",
        direction="outbound",
        occurred_at=datetime.now(tz=timezone.utc),
        content=rendered.body,
        subject=rendered.subject,
        provider_message_id=provider_message_id,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return EmailSendOut(provider_message_id=provider_message_id, interaction_id=interaction.id)
