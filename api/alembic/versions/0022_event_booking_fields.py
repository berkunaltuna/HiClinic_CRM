"""Default event-booking confirmation templates use {{event_date}}, {{slot}} and {{event_venue}}

Confirmations are only for people booked into an event slot in the Events tab;
the defaults now name the booking's values directly. Templates are only changed
if they still hold the text left by 0018-0021, so admin edits are kept.

Revision ID: 0022_event_booking_fields
Revises: 0021_plain_text_email_templates
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_event_booking_fields"
down_revision = "0021_plain_text_email_templates"
branch_labels = None
depends_on = None


# (channel, name, old subject, old body, new subject, new body)
TEMPLATES = [
    (
        'email',
        'auto_appointment_confirmation',
        'Your Health Clinic appointment is confirmed',
        'Hi {{first_name}},\n\nYour appointment with Health Clinic is confirmed.\n\n*Date:* {{appointment_date}}\n*Time:* {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})\n*Where:* {{appointment_location}}\n\nIf you need to change your appointment or have any questions, contact us on {{clinic_phone}} or {{clinic_email}}.\n\nKind regards,\n{{clinic_name}}',
        'Your Health Clinic booking is confirmed',
        'Hi {{first_name}},\n\nYour booking with Health Clinic is confirmed.\n\n*Date:* {{event_date}}\n*Time:* {{slot}}\n*Venue:* {{event_venue}}\n\nIf you need to change your booking or have any questions, contact us on {{clinic_phone}} or {{clinic_email}}.\n\nKind regards,\n{{clinic_name}}',
    ),
    (
        'whatsapp',
        'auto_appointment_confirmation',
        None,
        'Hi {{first_name}}, your Health Clinic appointment is confirmed for {{appointment_date}} at {{appointment_time}} ({{appointment_timezone}}), {{appointment_location}}. To change it, contact us on {{clinic_phone}}.',
        None,
        'Hi {{first_name}}, your Health Clinic booking is confirmed for {{event_date}}, {{slot}}, at {{event_venue}}. To change it, contact us on {{clinic_phone}}.',
    ),
    (
        'email',
        'auto_appointment_updated',
        'Your Health Clinic appointment has changed',
        "Hi {{first_name}},\n\nYour appointment with Health Clinic has been moved. Your new appointment is:\n\n*Date:* {{appointment_date}}\n*Time:* {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})\n*Where:* {{appointment_location}}\n\nIf this time doesn't suit you, contact us on {{clinic_phone}} or {{clinic_email}}.\n\nKind regards,\n{{clinic_name}}",
        'Your Health Clinic booking has changed',
        "Hi {{first_name}},\n\nYour booking with Health Clinic has been moved. Your new time is:\n\n*Date:* {{event_date}}\n*Time:* {{slot}}\n*Venue:* {{event_venue}}\n\nIf this time doesn't suit you, contact us on {{clinic_phone}} or {{clinic_email}}.\n\nKind regards,\n{{clinic_name}}",
    ),
    (
        'whatsapp',
        'auto_appointment_updated',
        None,
        'Hi {{first_name}}, your Health Clinic appointment has changed. New time: {{appointment_date}} at {{appointment_time}} ({{appointment_timezone}}), {{appointment_location}}. Questions? Contact us on {{clinic_phone}}.',
        None,
        'Hi {{first_name}}, your Health Clinic booking has changed. New time: {{event_date}}, {{slot}}, at {{event_venue}}. Questions? Contact us on {{clinic_phone}}.',
    ),
]


def _swap(channel: str, name: str, old_subject, old_body: str, new_subject, new_body: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE templates SET subject = :new_subject, body = :new_body, updated_at = now() "
            "WHERE channel = :c AND name = :n AND language = 'und' AND body = :old_body "
            "AND subject IS NOT DISTINCT FROM :old_subject"
        ),
        {"c": channel, "n": name, "old_subject": old_subject, "old_body": old_body, "new_subject": new_subject, "new_body": new_body},
    )


def upgrade() -> None:
    for channel, name, old_subject, old_body, new_subject, new_body in TEMPLATES:
        _swap(channel, name, old_subject, old_body, new_subject, new_body)


def downgrade() -> None:
    for channel, name, old_subject, old_body, new_subject, new_body in TEMPLATES:
        _swap(channel, name, new_subject, new_body, old_subject, old_body)
