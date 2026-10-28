"""Care team: doctor_assistant role, doctor/assistant assignments, doctor profiles,
patient documents (proformas), photo request emails, photo request email template

Revision ID: 0025_care_team_documents
Revises: 0024_patient_photo_requests
Create Date: 2026-10-27
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0025_care_team_documents"
down_revision = "0024_patient_photo_requests"
branch_labels = None
depends_on = None

PHOTO_EMAIL_TEMPLATE = "photo_request_link"
PHOTO_EMAIL_SUBJECT = "Your secure photo upload link"
# No clinical details and no attachments: just the personal, expiring link.
PHOTO_EMAIL_BODY = (
    "Hi {{first_name}},\n\n"
    "The clinic has asked you to share some photos. Please use your personal, secure link to upload them:\n\n"
    "{{portal_link}}\n\n"
    "The link expires on {{link_expires}}. Please do not forward it to anyone.\n\n"
    "Please don't reply to this email with photos. Only upload them through the link above.\n\n"
    "If you weren't expecting this message, please contact the clinic."
)


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor_assistant'")

    op.create_table(
        "doctor_patient_assignments",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("doctor_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        _user_fk("assigned_by_user_id"),
        _created_at(),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        _user_fk("ended_by_user_id"),
    )
    op.create_index(
        "uq_doctor_patient_active", "doctor_patient_assignments", ["customer_id"], unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index("ix_doctor_patient_doctor", "doctor_patient_assignments", ["doctor_user_id", "ended_at"])

    op.create_table(
        "assistant_doctor_assignments",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("assistant_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doctor_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        _user_fk("assigned_by_user_id"),
        _created_at(),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        _user_fk("ended_by_user_id"),
    )
    op.create_index(
        "uq_assistant_doctor_active", "assistant_doctor_assignments", ["assistant_user_id", "doctor_user_id"], unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "doctor_profiles",
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column("title", sa.String(200)),
        sa.Column("specialty", sa.String(200)),
        sa.Column("bio", sa.Text()),
        sa.Column("visible_to_patients", sa.Boolean(), nullable=False, server_default=sa.false()),
        _user_fk("updated_by_user_id"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "patient_documents",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        _user_fk("uploaded_by_user_id"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("category IN ('proforma')", name="ck_patient_documents_category"),
    )
    op.create_index("ix_patient_documents_customer", "patient_documents", ["customer_id", "category", "superseded_at"])

    op.create_table(
        "photo_request_emails",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_id", sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_id", sa.UUID(as_uuid=True), sa.ForeignKey("photo_access_links.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("outbound_message_id", sa.UUID(as_uuid=True), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_email", sa.String(320), nullable=False),
        _user_fk("sent_by_user_id"),
        _created_at(),
    )
    op.create_index("ix_photo_request_emails_request", "photo_request_emails", ["request_id", "created_at"])

    # Editable on the Templates page; sending checks it still contains {{portal_link}}.
    op.execute(
        sa.text(
            "INSERT INTO templates (id, channel, name, subject, body, category, language, created_at, updated_at) "
            "VALUES (:id, 'email', :name, :subject, :body, 'transactional', 'und', now(), now()) "
            "ON CONFLICT ON CONSTRAINT uq_templates_channel_name_language DO NOTHING"
        ).bindparams(id=uuid.uuid4(), name=PHOTO_EMAIL_TEMPLATE, subject=PHOTO_EMAIL_SUBJECT, body=PHOTO_EMAIL_BODY)
    )


def downgrade() -> None:
    # Proforma files in storage are not touched; 'doctor_assistant' stays in the enum.
    op.execute(sa.text("DELETE FROM templates WHERE channel = 'email' AND name = :n").bindparams(n=PHOTO_EMAIL_TEMPLATE))
    op.drop_table("photo_request_emails")
    op.drop_table("patient_documents")
    op.drop_table("doctor_profiles")
    op.drop_table("assistant_doctor_assignments")
    op.drop_table("doctor_patient_assignments")
