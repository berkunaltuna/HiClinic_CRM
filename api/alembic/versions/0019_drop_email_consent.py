"""Drop customers.email_consent: an email left on a lead form counts as permission to email

Revision ID: 0019_drop_email_consent
Revises: 0018_messaging_automations
Create Date: 2026-10-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_drop_email_consent"
down_revision = "0018_messaging_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("customers", "email_consent")


def downgrade() -> None:
    op.add_column("customers", sa.Column("email_consent", sa.Boolean(), nullable=True))
