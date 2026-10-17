"""Recipient review: staff approval mode, stored message payloads, approved WhatsApp templates

Revision ID: 0023_recipient_review
Revises: 0022_event_booking_fields
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_recipient_review"
down_revision = "0022_event_booking_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set by an admin once WhatsApp has approved the Twilio Content template; cleared
    # whenever the template text or SID changes. Automations never send WhatsApp without it.
    op.add_column("templates", sa.Column("provider_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messaging_automations", sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Exactly what will be handed to the worker (template id, body, variables), so an
    # approved message is the same content staff previewed.
    op.add_column("automation_sends", sa.Column("payload", sa.JSON(), nullable=True))
    # Set when a staff member approves the message; the payload then also records the
    # booking date/slot/venue it was approved with, re-checked right before sending.
    op.add_column("automation_sends", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "automation_sends",
        sa.Column("approved_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("automation_sends", "approved_by_user_id")
    op.drop_column("automation_sends", "approved_at")
    op.drop_column("automation_sends", "payload")
    op.drop_column("messaging_automations", "require_approval")
    op.drop_column("templates", "provider_approved_at")
