"""Drop customers.whatsapp_consent and add an opt-out line to the default lead follow-up templates

Contact details left on a lead form now count as permission for both email and
WhatsApp; customers.can_contact is the opt-out. The follow-up templates are only
updated if they still hold the text seeded by 0018, so admin edits are kept.

Revision ID: 0020_whatsapp_consent_optout
Revises: 0019_drop_email_consent
Create Date: 2026-10-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_whatsapp_consent_optout"
down_revision = "0019_drop_email_consent"
branch_labels = None
depends_on = None


_EMAIL_OLD = (
    "<p>Hi {{first_name}},</p>"
    "<p>Thank you for your enquiry with Health Clinic. We'd be happy to answer any questions and help you book a consultation.</p>"
    "<p>Just reply to this email or contact us on {{clinic_phone}}.</p>"
    "<p>Kind regards,<br>{{clinic_name}}</p>"
)
_EMAIL_NEW = _EMAIL_OLD + (
    "<p style=\"font-size:12px;color:#6b7280\">If you'd rather not hear from us, reply STOP and we won't email you again.</p>"
)
_WHATSAPP_OLD = (
    "Hi {{first_name}}, thanks for your enquiry with Health Clinic. "
    "Would you like help booking a consultation? Reply here or call {{clinic_phone}}."
)
_WHATSAPP_NEW = _WHATSAPP_OLD + " Reply STOP to opt out."


def _swap(channel: str, old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE templates SET body = :new, updated_at = now() "
            "WHERE channel = :c AND name = 'auto_lead_followup' AND language = 'und' AND body = :old"
        ),
        {"c": channel, "old": old, "new": new},
    )


def upgrade() -> None:
    op.drop_column("customers", "whatsapp_consent")
    _swap("email", _EMAIL_OLD, _EMAIL_NEW)
    _swap("whatsapp", _WHATSAPP_OLD, _WHATSAPP_NEW)


def downgrade() -> None:
    _swap("whatsapp", _WHATSAPP_NEW, _WHATSAPP_OLD)
    _swap("email", _EMAIL_NEW, _EMAIL_OLD)
    op.add_column("customers", sa.Column("whatsapp_consent", sa.Boolean(), nullable=True))
