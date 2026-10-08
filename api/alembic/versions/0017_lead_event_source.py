"""Record the platform (and Google click id / test flag) of each ad lead submission

Revision ID: 0017_lead_event_source
Revises: 0016_event_import
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_lead_event_source"
down_revision = "0016_event_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facebook_lead_events",
        sa.Column("source", sa.String(length=40), nullable=False, server_default="facebook"),
    )
    op.add_column("facebook_lead_events", sa.Column("gclid", sa.String(length=500), nullable=True))
    op.add_column(
        "facebook_lead_events",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("facebook_lead_events", "is_test")
    op.drop_column("facebook_lead_events", "gclid")
    op.drop_column("facebook_lead_events", "source")
