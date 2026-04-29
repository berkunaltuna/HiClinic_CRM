"""Phase 4B/4C: inbound WhatsApp + automation workflows + scheduling

Revision ID: 0005_phase4b4c
Revises: 0004_phase4
Create Date: 2026-02-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_phase4b4c"
down_revision = "0004_phase4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Outbound messages can be scheduled
    with op.batch_alter_table("outbound_messages") as batch:
        batch.add_column(sa.Column("not_before_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_outbound_messages_status_notbefore",
        "outbound_messages",
        ["status", "not_before_at"],
    )

    # Automation workflows (Phase 4C)
    op.create_table(
        "workflows",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("trigger_event", sa.String(length=80), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workflows_owner_event", "workflows", ["owner_user_id", "trigger_event"])


def downgrade() -> None:
    op.drop_index("ix_workflows_owner_event", table_name="workflows")
    op.drop_table("workflows")

    op.drop_index("ix_outbound_messages_status_notbefore", table_name="outbound_messages")
    with op.batch_alter_table("outbound_messages") as batch:
        batch.drop_column("not_before_at")
