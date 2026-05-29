"""Phase 6B: store mapped Facebook lead form answers on deals

Revision ID: 0011_phase6b_lead_form_answers
Revises: 0010_phase6_delete_fk_hardening
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_phase6b_lead_form_answers"
down_revision = "0010_phase6_delete_fk_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("treatment_interest", sa.String(length=200), nullable=True))
    op.add_column("deals", sa.Column("preferred_consultation_day", sa.String(length=200), nullable=True))
    op.add_column("deals", sa.Column("seminar_preference", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "seminar_preference")
    op.drop_column("deals", "preferred_consultation_day")
    op.drop_column("deals", "treatment_interest")
