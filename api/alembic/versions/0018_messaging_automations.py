"""Messaging automations: per-channel consent, clinic contact, automation settings and send log

Revision ID: 0018_messaging_automations
Revises: 0017_lead_event_source
Create Date: 2026-10-14
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0018_messaging_automations"
down_revision = "0017_lead_event_source"
branch_labels = None
depends_on = None


# Default templates seeded once (only if no template with that channel/name/language
# exists yet). Admins edit them from the Workflows page. No clinical details in
# subjects or WhatsApp copy.
DEFAULT_TEMPLATES = [
    (
        "email",
        "auto_appointment_confirmation",
        "Your Health Clinic appointment is confirmed",
        "<p>Hi {{first_name}},</p>"
        "<p>Your appointment with Health Clinic is confirmed.</p>"
        "<p><b>Date:</b> {{appointment_date}}<br>"
        "<b>Time:</b> {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})<br>"
        "<b>Where:</b> {{appointment_location}}</p>"
        "<p>If you need to change your appointment or have any questions, contact us on {{clinic_phone}} or {{clinic_email}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>",
    ),
    (
        "whatsapp",
        "auto_appointment_confirmation",
        None,
        "Hi {{first_name}}, your Health Clinic appointment is confirmed for {{appointment_date}} at "
        "{{appointment_time}} ({{appointment_timezone}}), {{appointment_location}}. "
        "To change it, contact us on {{clinic_phone}}.",
    ),
    (
        "email",
        "auto_appointment_updated",
        "Your Health Clinic appointment has changed",
        "<p>Hi {{first_name}},</p>"
        "<p>Your appointment with Health Clinic has been moved. Your new appointment is:</p>"
        "<p><b>Date:</b> {{appointment_date}}<br>"
        "<b>Time:</b> {{appointment_time}} to {{appointment_end_time}} ({{appointment_timezone}})<br>"
        "<b>Where:</b> {{appointment_location}}</p>"
        "<p>If this time doesn't suit you, contact us on {{clinic_phone}} or {{clinic_email}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>",
    ),
    (
        "whatsapp",
        "auto_appointment_updated",
        None,
        "Hi {{first_name}}, your Health Clinic appointment has changed. New time: {{appointment_date}} at "
        "{{appointment_time}} ({{appointment_timezone}}), {{appointment_location}}. "
        "Questions? Contact us on {{clinic_phone}}.",
    ),
    (
        "email",
        "auto_lead_followup",
        "Following up on your Health Clinic enquiry",
        "<p>Hi {{first_name}},</p>"
        "<p>Thank you for your enquiry with Health Clinic. We'd be happy to answer any questions and help you book a consultation.</p>"
        "<p>Just reply to this email or contact us on {{clinic_phone}}.</p>"
        "<p>Kind regards,<br>{{clinic_name}}</p>",
    ),
    (
        "whatsapp",
        "auto_lead_followup",
        None,
        "Hi {{first_name}}, thanks for your enquiry with Health Clinic. "
        "Would you like help booking a consultation? Reply here or call {{clinic_phone}}.",
    ),
]


def upgrade() -> None:
    op.add_column("customers", sa.Column("email_consent", sa.Boolean(), nullable=True))
    op.add_column("customers", sa.Column("whatsapp_consent", sa.Boolean(), nullable=True))
    op.add_column("customers", sa.Column("consent_source", sa.String(length=200), nullable=True))
    op.add_column("customers", sa.Column("consent_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "clinic_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_name", sa.String(length=200), nullable=False, server_default="Health Clinic"),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "messaging_automations",
        sa.Column("key", sa.String(length=60), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("send_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("update_email_template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("update_whatsapp_template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delay_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("max_per_run", sa.Integer(), nullable=True),
        sa.Column("active_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "automation_sends",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("automation_key", sa.String(length=60), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("appointment_id", sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("slot_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slot_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rendered_subject", sa.Text(), nullable=True),
        sa.Column("rendered_body", sa.Text(), nullable=True),
        sa.Column("outbound_message_id", sa.UUID(as_uuid=True), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_automation_sends_key_status", "automation_sends", ["automation_key", "status"])
    op.create_index("ix_automation_sends_customer", "automation_sends", ["customer_id"])
    op.create_index("ix_automation_sends_appointment", "automation_sends", ["appointment_id"])

    conn = op.get_bind()
    for channel, name, subject, body in DEFAULT_TEMPLATES:
        exists = conn.execute(
            sa.text("SELECT 1 FROM templates WHERE channel = :c AND name = :n AND language = 'und'"),
            {"c": channel, "n": name},
        ).first()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO templates (id, channel, name, subject, body, category, language, created_at, updated_at) "
                "VALUES (:id, :c, :n, :s, :b, 'transactional', 'und', now(), now())"
            ),
            {"id": str(uuid.uuid4()), "c": channel, "n": name, "s": subject, "b": body},
        )


def downgrade() -> None:
    op.drop_index("ix_automation_sends_appointment", table_name="automation_sends")
    op.drop_index("ix_automation_sends_customer", table_name="automation_sends")
    op.drop_index("ix_automation_sends_key_status", table_name="automation_sends")
    op.drop_table("automation_sends")
    op.drop_table("messaging_automations")
    op.drop_table("clinic_settings")
    op.drop_column("customers", "consent_updated_at")
    op.drop_column("customers", "consent_source")
    op.drop_column("customers", "whatsapp_consent")
    op.drop_column("customers", "email_consent")
