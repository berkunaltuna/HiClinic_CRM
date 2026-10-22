"""Patient photo requests: doctor role, requests, access links, photo metadata, notes, assessments

Revision ID: 0024_patient_photo_requests
Revises: 0023_recipient_review
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_patient_photo_requests"
down_revision = "0023_recipient_review"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _request_fk() -> sa.Column:
    return sa.Column("request_id", sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    # ADD VALUE cannot run inside the migration's transaction on older Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor'")

    op.create_table(
        "photo_requests",
        _id(),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("appointment_id", sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", sa.UUID(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True),
        _user_fk("created_by_user_id"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("instructions", sa.Text()),
        sa.Column("patient_message", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="requested"),
        sa.Column("upload_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("consent_version", sa.String(40)),
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True)),
        sa.Column("consent_link_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('requested','uploaded','in_review','more_photos_needed','reviewed','closed','withdrawn')",
            name="ck_photo_requests_status",
        ),
    )
    op.create_index("ix_photo_requests_customer", "photo_requests", ["customer_id", "created_at"])
    op.create_index("ix_photo_requests_status", "photo_requests", ["status", "updated_at"])

    op.create_table(
        "photo_access_links",
        _id(),
        _request_fk(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        _user_fk("created_by_user_id"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _user_fk("revoked_by_user_id"),
        sa.Column("revoke_reason", sa.String(200)),
        _created_at(),
    )
    op.create_index("ix_photo_access_links_request", "photo_access_links", ["request_id"])

    op.create_table(
        "patient_photos",
        _id(),
        _request_fk(),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("upload_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "uploaded_via_link_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("photo_access_links.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _user_fk("deleted_by_user_id"),
        sa.Column("delete_reason", sa.String(200)),
    )
    op.create_index("ix_patient_photos_request", "patient_photos", ["request_id", "upload_round"])

    for table in ("photo_request_notes", "photo_clinical_assessments"):
        op.create_table(
            table,
            _id(),
            _request_fk(),
            _user_fk("author_user_id"),
            sa.Column("author_email", sa.String(320)),
            sa.Column("author_role", sa.String(30), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            _created_at(),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(f"ix_{table}_request", table, ["request_id", "created_at"])

    op.create_table(
        "photo_entry_revisions",
        _id(),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("entry_id", sa.UUID(as_uuid=True), nullable=False),
        _request_fk(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        _user_fk("editor_user_id"),
        sa.Column("editor_email", sa.String(320)),
        sa.Column("editor_role", sa.String(30), nullable=False),
        _created_at(),
        sa.UniqueConstraint("entry_type", "entry_id", "version", name="uq_photo_entry_revisions_version"),
    )
    op.create_index("ix_photo_entry_revisions_entry", "photo_entry_revisions", ["entry_type", "entry_id"])

    op.create_table(
        "photo_request_status_events",
        _id(),
        _request_fk(),
        sa.Column("from_status", sa.String(30)),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        _user_fk("actor_user_id"),
        sa.Column("actor_email", sa.String(320)),
        sa.Column("actor_role", sa.String(30)),
        sa.Column("reason", sa.Text()),
        _created_at(),
    )
    op.create_index(
        "ix_photo_request_status_events_request", "photo_request_status_events", ["request_id", "created_at"]
    )


def downgrade() -> None:
    # Photo bytes in PHOTO_STORAGE_DIR are not touched. Postgres cannot drop an enum
    # value, so 'doctor' stays in user_role (unused once no user holds it).
    op.drop_table("photo_request_status_events")
    op.drop_table("photo_entry_revisions")
    op.drop_table("photo_clinical_assessments")
    op.drop_table("photo_request_notes")
    op.drop_table("patient_photos")
    op.drop_table("photo_access_links")
    op.drop_table("photo_requests")
