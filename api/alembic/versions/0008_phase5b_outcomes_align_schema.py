"""Phase 5B: align outcome_events schema with application model

Revision ID: 0008_phase5b_outcomes_align
Revises: 0007_phase5b_outcomes
Create Date: 2026-02-28

This migration fixes a drift that can happen during iterative development:
- The original Phase 5B migration created an enum column named "outcome".
- The application code uses the concept "type" and stores optional fields
  (amount, metadata).

We keep the DB column name "outcome" (and map it in SQLAlchemy), and add the
missing optional columns so inserts/reads work reliably.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_phase5b_outcomes_align"
down_revision = "0007_phase5b_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add optional columns expected by the application.
    op.add_column("outcome_events", sa.Column("amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("outcome_events", sa.Column("metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("outcome_events", "metadata")
    op.drop_column("outcome_events", "amount")
