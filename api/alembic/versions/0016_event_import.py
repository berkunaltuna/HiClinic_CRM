"""Event booking Excel/CSV import batches and rows

Revision ID: 0016_event_import
Revises: 0015_deal_quote_amount
Create Date: 2026-10-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_event_import"
down_revision = "0015_deal_quote_amount"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def upgrade() -> None:
    if not _has_table("import_batches"):
        op.create_table(
            "import_batches",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("event_id", sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_name_snapshot", sa.String(length=200), nullable=True),
            sa.Column("source_filename", sa.String(length=300), nullable=True),
            sa.Column("source_format", sa.String(length=10), nullable=False),
            sa.Column("mapping", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="uploaded", nullable=False),
            sa.Column("committing_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("customers_created", sa.Integer(), server_default="0", nullable=False),
            sa.Column("customers_updated", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rows_unchanged", sa.Integer(), server_default="0", nullable=False),
            sa.Column("duplicates_merged", sa.Integer(), server_default="0", nullable=False),
            sa.Column("bookings_created", sa.Integer(), server_default="0", nullable=False),
            sa.Column("bookings_updated", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rows_flagged", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_import_batches_event", "import_batches", ["event_id"])
        op.create_index("ix_import_batches_owner", "import_batches", ["owner_user_id"])

    if not _has_table("import_rows"):
        op.create_table(
            "import_rows",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("batch_id", sa.UUID(as_uuid=True), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("raw_data", sa.JSON(), nullable=False),
            sa.Column("mapped_data", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
            sa.Column("match_type", sa.String(length=20), nullable=True),
            sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
            sa.Column("appointment_id", sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reasons", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("batch_id", "row_number", name="uq_import_rows_batch_row"),
        )
        op.create_index("ix_import_rows_batch_status", "import_rows", ["batch_id", "status"])


def downgrade() -> None:
    if _has_table("import_rows"):
        op.drop_index("ix_import_rows_batch_status", table_name="import_rows")
        op.drop_table("import_rows")
    if _has_table("import_batches"):
        op.drop_index("ix_import_batches_owner", table_name="import_batches")
        op.drop_index("ix_import_batches_event", table_name="import_batches")
        op.drop_table("import_batches")
