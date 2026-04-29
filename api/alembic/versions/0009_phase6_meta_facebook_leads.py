"""Phase 6: Meta/Facebook lead webhook ingestion

Revision ID: 0009_phase6_meta_facebook_leads
Revises: 0008_phase5b_outcomes_align
Create Date: 2026-03-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_phase6_meta_facebook_leads"
down_revision = "0008_phase5b_outcomes_align"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facebook_lead_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("leadgen_id", sa.String(length=120), nullable=False),
        sa.Column("page_id", sa.String(length=120), nullable=True),
        sa.Column("form_id", sa.String(length=120), nullable=True),
        sa.Column("campaign_id", sa.String(length=120), nullable=True),
        sa.Column("adset_id", sa.String(length=120), nullable=True),
        sa.Column("ad_id", sa.String(length=120), nullable=True),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("deal_id", sa.UUID(as_uuid=True), sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("leadgen_id", name="uq_facebook_lead_events_leadgen_id"),
    )
    op.create_index(
        "ix_facebook_lead_events_owner_created",
        "facebook_lead_events",
        ["owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_facebook_lead_events_owner_created", table_name="facebook_lead_events")
    op.drop_table("facebook_lead_events")
