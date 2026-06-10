"""Phase 8: pipeline productivity and lead attribution

Revision ID: 0013_phase8_pipeline
Revises: 0012_phase7_users_audit_events
Create Date: 2026-06-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_phase8_pipeline"
down_revision = "0012_phase7_users_audit_events"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column_name: str) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns(table)}
    if column_name in existing:
        op.drop_column(table, column_name)


def upgrade() -> None:
    for name, length in [
        ("lead_source", 120), ("form_id", 120), ("form_name", 250),
        ("campaign_id", 120), ("campaign_name", 250), ("adset_id", 120),
        ("adset_name", 250), ("ad_id", 120), ("ad_name", 250),
    ]:
        _add_column_if_missing("customers", sa.Column(name, sa.String(length=length), nullable=True))

    _add_column_if_missing("deals", sa.Column("event_id", sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True))
    _add_column_if_missing("deals", sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("deals", sa.Column("confirmation_channel", sa.String(length=40), nullable=True))
    _add_column_if_missing("deals", sa.Column("confirmation_template_id", sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True))
    _add_column_if_missing("deals", sa.Column("confirmed_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    _add_column_if_missing("deals", sa.Column("lost_reason", sa.String(length=200), nullable=True))

    for name, length in [("campaign_name", 250), ("adset_name", 250), ("ad_name", 250), ("form_name", 250)]:
        _add_column_if_missing("facebook_lead_events", sa.Column(name, sa.String(length=length), nullable=True))

    op.create_index("ix_deals_event", "deals", ["event_id"], if_not_exists=True)
    op.create_index("ix_deals_lost_reason", "deals", ["lost_reason"], if_not_exists=True)
    op.create_index("ix_customers_campaign_name", "customers", ["campaign_name"], if_not_exists=True)
    op.create_index("ix_customers_ad_name", "customers", ["ad_name"], if_not_exists=True)


def downgrade() -> None:
    for idx, table in [
        ("ix_customers_ad_name", "customers"),
        ("ix_customers_campaign_name", "customers"),
        ("ix_deals_lost_reason", "deals"),
        ("ix_deals_event", "deals"),
    ]:
        try:
            op.drop_index(idx, table_name=table)
        except Exception:
            pass
    for name in ["form_name", "ad_name", "adset_name", "campaign_name"]:
        _drop_column_if_exists("facebook_lead_events", name)
    for name in ["lost_reason", "confirmed_by_user_id", "confirmation_template_id", "confirmation_channel", "confirmation_sent_at", "event_id"]:
        _drop_column_if_exists("deals", name)
    for name in ["ad_name", "ad_id", "adset_name", "adset_id", "campaign_name", "campaign_id", "form_name", "form_id", "lead_source"]:
        _drop_column_if_exists("customers", name)
