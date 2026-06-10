"""Add editable event slot capacity

Revision ID: 0014_slot_capacity
Revises: 0013_phase8_pipeline
Create Date: 2026-06-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_slot_capacity"
down_revision = "0013_phase8_pipeline"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_check(table: str, name: str) -> bool:
    return name in {c["name"] for c in _inspector().get_check_constraints(table)}


def upgrade() -> None:
    if not _has_column("events", "slot_capacity"):
        op.add_column("events", sa.Column("slot_capacity", sa.Integer(), nullable=False, server_default="1"))
    if not _has_check("events", "ck_events_slot_capacity_positive"):
        op.create_check_constraint("ck_events_slot_capacity_positive", "events", "slot_capacity >= 1")


def downgrade() -> None:
    if _has_check("events", "ck_events_slot_capacity_positive"):
        op.drop_constraint("ck_events_slot_capacity_positive", "events", type_="check")
    if _has_column("events", "slot_capacity"):
        op.drop_column("events", "slot_capacity")
