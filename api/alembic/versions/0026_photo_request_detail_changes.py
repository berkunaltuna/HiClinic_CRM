"""Editable photo request details: change history and the "request updated" email template

Revision ID: 0026_photo_request_edits
Revises: 0025_care_team_documents
Create Date: 2026-10-28
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0026_photo_request_edits"
down_revision = "0025_care_team_documents"
branch_labels = None
depends_on = None

UPDATED_TEMPLATE = "photo_request_updated"
UPDATED_SUBJECT = "Your photo request has been updated"
# Like the first email: only the personal link, no clinical details or attachments.
UPDATED_BODY = (
    "Hi {{first_name}},\n\n"
    "The clinic has updated its request for photos. Please open your personal, secure link to see what is needed now:\n\n"
    "{{portal_link}}\n\n"
    "The link expires on {{link_expires}}. Any link we sent you earlier for this request still works too. "
    "Please do not forward it to anyone.\n\n"
    "Please don't reply to this email with photos. Only upload them through the link above.\n\n"
    "If you weren't expecting this message, please contact the clinic."
)


def upgrade() -> None:
    op.create_table(
        "photo_request_detail_changes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_id", sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_by_email", sa.String(320)),
        sa.Column("changed_by_role", sa.String(30), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("patient_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_photo_request_detail_changes_request", "photo_request_detail_changes", ["request_id", "created_at"])
    op.execute(
        sa.text(
            "INSERT INTO templates (id, channel, name, subject, body, category, language, created_at, updated_at) "
            "VALUES (:id, 'email', :name, :subject, :body, 'transactional', 'und', now(), now()) "
            "ON CONFLICT ON CONSTRAINT uq_templates_channel_name_language DO NOTHING"
        ).bindparams(id=uuid.uuid4(), name=UPDATED_TEMPLATE, subject=UPDATED_SUBJECT, body=UPDATED_BODY)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM templates WHERE channel = 'email' AND name = :n").bindparams(n=UPDATED_TEMPLATE))
    op.drop_table("photo_request_detail_changes")
