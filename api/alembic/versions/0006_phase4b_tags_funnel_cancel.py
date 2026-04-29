"""Phase 4B/4C: tags + customer stage + cancel-on-inbound

Revision ID: 0006_phase4b_tags
Revises: 0005_phase4b4c
Create Date: 2026-02-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_phase4b_tags"
down_revision = "0005_phase4b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Customer funnel stage
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("stage", sa.String(length=40), nullable=False, server_default="new"))

    # Tags
    op.create_table(
        "tags",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_tags_owner_name"),
    )

    op.create_table(
        "customer_tags",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("tag_id", sa.UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_customer_tag"),
    )

    op.create_index(
        "ix_customer_tags_owner_customer",
        "customer_tags",
        ["owner_user_id", "customer_id"],
    )

    # Cancel queued outbound messages when an inbound reply arrives
    with op.batch_alter_table("outbound_messages") as batch:
        batch.add_column(sa.Column("cancel_on_inbound", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outbound_messages") as batch:
        batch.drop_column("cancelled_at")
        batch.drop_column("cancel_on_inbound")

    op.drop_index("ix_customer_tags_owner_customer", table_name="customer_tags")
    op.drop_table("customer_tags")
    op.drop_table("tags")

    with op.batch_alter_table("customers") as batch:
        batch.drop_column("stage")
