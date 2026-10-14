"""Rewrite the default automation email templates as plain text

Emails are now written as plain text and laid out as HTML when sent (blank line =
new paragraph, *text* = bold, links clickable). Only templates still holding the
seeded HTML are converted, so admin edits are kept.

Revision ID: 0021_plain_text_email_templates
Revises: 0020_whatsapp_consent_optout
Create Date: 2026-10-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_plain_text_email_templates"
down_revision = "0020_whatsapp_consent_optout"
branch_labels = None
depends_on = None


_SLOT_HTML = (
    "<p><b>Date:</b> {{appointment_date}}<br>"
    "<b>Time:</b> {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})<br>"
    "<b>Where:</b> {{appointment_location}}</p>"
)
_SLOT_TEXT = (
    "*Date:* {{appointment_date}}\n"
    "*Time:* {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})\n"
    "*Where:* {{appointment_location}}"
)

# (name, seeded HTML, plain-text replacement)
TEMPLATES = [
    (
        "auto_appointment_confirmation",
        "<p>Hi {{first_name}},</p>"
        "<p>Your appointment with Health Clinic is confirmed.</p>"
        + _SLOT_HTML
        + "<p>If you need to change your appointment or have any questions, contact us on {{clinic_phone}} or {{clinic_email}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>",
        "Hi {{first_name}},\n\n"
        "Your appointment with Health Clinic is confirmed.\n\n"
        + _SLOT_TEXT
        + "\n\nIf you need to change your appointment or have any questions, contact us on {{clinic_phone}} or {{clinic_email}}.\n\n"
        "Kind regards,\n{{clinic_name}}",
    ),
    (
        "auto_appointment_updated",
        "<p>Hi {{first_name}},</p>"
        "<p>Your appointment with Health Clinic has been moved. Your new appointment is:</p>"
        + _SLOT_HTML
        + "<p>If this time doesn't suit you, contact us on {{clinic_phone}} or {{clinic_email}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>",
        "Hi {{first_name}},\n\n"
        "Your appointment with Health Clinic has been moved. Your new appointment is:\n\n"
        + _SLOT_TEXT
        + "\n\nIf this time doesn't suit you, contact us on {{clinic_phone}} or {{clinic_email}}.\n\n"
        "Kind regards,\n{{clinic_name}}",
    ),
    (
        "auto_lead_followup",
        "<p>Hi {{first_name}},</p>"
        "<p>Thank you for your enquiry with Health Clinic. We'd be happy to answer any questions and help you book a consultation.</p>"
        "<p>Just reply to this email or contact us on {{clinic_phone}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>"
        "<p style=\"font-size:12px;color:#6b7280\">If you'd rather not hear from us, reply STOP and we won't email you again.</p>",
        "Hi {{first_name}},\n\n"
        "Thank you for your enquiry with Health Clinic. We'd be happy to answer any questions and help you book a consultation.\n\n"
        "Just reply to this email or contact us on {{clinic_phone}}.\n\n"
        "Kind regards,\n{{clinic_name}}\n\n"
        "If you'd rather not hear from us, reply STOP and we won't email you again.",
    ),
]


def _swap(name: str, old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE templates SET body = :new, updated_at = now() "
            "WHERE channel = 'email' AND name = :n AND language = 'und' AND body = :old"
        ),
        {"n": name, "old": old, "new": new},
    )


def upgrade() -> None:
    for name, old_html, text in TEMPLATES:
        _swap(name, old_html, text)


def downgrade() -> None:
    for name, old_html, text in TEMPLATES:
        _swap(name, text, old_html)
