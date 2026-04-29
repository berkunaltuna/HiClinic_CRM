"""Phase 5B: outcome events for KPI dashboards

Revision ID: 0007_phase5b_outcomes
Revises: 0006_phase4b_tags
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_phase5b_outcomes"
down_revision = "0006_phase4b_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enum types are global objects. During iterative dev/test cycles it's common
    # to rerun migrations against a database that already has the enum.
    #
    # IMPORTANT:
    # - We set create_type=False so SQLAlchemy will NOT auto-create the enum during
    #   CREATE TABLE (which can raise DuplicateObject).
    # - We create/drop the enum explicitly with a safe DO block.
    outcome_type = sa.Enum(
        "consult_booked",
        "deposit_paid",
        "treatment_done",
        "lost",
        name="outcome_type",
        create_type=False,
    )

    # op.execute(
    #     """
    #     DO $$
    #     BEGIN
    #         IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'outcome_type') THEN
    #             CREATE TYPE outcome_type AS ENUM ('consult_booked', 'deposit_paid', 'treatment_done', 'lost');
    #         END IF;
    #     END $$;
    #     """
    # )

    # ✅ Now create the table(s) that use outcome_type
    op.create_table(
        "outcome_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", outcome_type, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


    op.create_index(
        "ix_outcome_events_owner_occurred",
        "outcome_events",
        ["owner_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_outcome_events_owner_outcome",
        "outcome_events",
        ["owner_user_id", "outcome"],
    )



def downgrade() -> None:
    op.drop_index("ix_outcome_events_owner_outcome", table_name="outcome_events")
    op.drop_index("ix_outcome_events_owner_occurred", table_name="outcome_events")
    op.drop_table("outcome_events")

    # op.execute(
    #     """
    #     DO $$
    #     BEGIN
    #         IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'outcome_type') THEN
    #             DROP TYPE outcome_type;
    #         END IF;
    #     END $$;
    #     """
    # )