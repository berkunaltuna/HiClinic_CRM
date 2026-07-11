"""Add quote_amount to deals

Revision ID: 0015_deal_quote_amount
Revises: 0014_slot_capacity
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_deal_quote_amount"
down_revision = "0014_slot_capacity"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def upgrade() -> None:
    if not _has_column("deals", "quote_amount"):
        op.add_column("deals", sa.Column("quote_amount", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    if _has_column("deals", "quote_amount"):
        op.drop_column("deals", "quote_amount")
