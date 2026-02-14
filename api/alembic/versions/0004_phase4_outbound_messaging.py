"""Phase 4 outbound messaging queue (WhatsApp/SMS) + provider template id

Revision ID: 0004_phase4
Revises: 0003_phase3
Create Date: 2026-02-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_phase4"
down_revision = "0003_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Templates: allow linking to provider-side templates (e.g. Twilio Content SID)
    with op.batch_alter_table("templates") as batch:
        batch.add_column(sa.Column("provider_template_id", sa.String(length=120), nullable=True))

    # Outbound message queue for worker processing
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id"), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("variables", sa.JSON(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_outbound_messages_owner_created", "outbound_messages", ["owner_user_id", "created_at"])
    op.create_index("ix_outbound_messages_status", "outbound_messages", ["status"])


def downgrade() -> None:
    op.drop_index("ix_outbound_messages_status", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_owner_created", table_name="outbound_messages")
    op.drop_table("outbound_messages")

    with op.batch_alter_table("templates") as batch:
        batch.drop_column("provider_template_id")
