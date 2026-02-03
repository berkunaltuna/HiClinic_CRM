"""Phase 3 email execution fields

Revision ID: 0003_phase3
Revises: 0002_phase2
Create Date: 2026-01-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_phase3"
down_revision = "0002_phase2"
branch_labels = None
depends_on = None

template_category_enum = postgresql.ENUM(
    "transactional",
    "marketing",
    name="template_category",
    create_type=False,
)


def upgrade() -> None:
    # Idempotent enum creation
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE template_category AS ENUM ('transactional', 'marketing');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # Customers: consent + language
    op.add_column(
        "customers",
        sa.Column("can_contact", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("customers", sa.Column("language", sa.String(length=10), nullable=True))

    # Templates: category + language (default/unspecified = 'und')
    op.add_column(
        "templates",
        sa.Column("category", template_category_enum, nullable=False, server_default="transactional"),
    )
    op.add_column(
        "templates",
        sa.Column("language", sa.String(length=10), nullable=False, server_default="und"),
    )

    # Replace unique constraint
    op.drop_constraint("uq_templates_channel_name", "templates", type_="unique")
    op.create_unique_constraint(
        "uq_templates_channel_name_language",
        "templates",
        ["channel", "name", "language"],
    )

    op.create_index("ix_templates_language", "templates", ["language"], unique=False)
    op.create_index("ix_templates_category", "templates", ["category"], unique=False)

    # Interactions: email metadata
    op.add_column("interactions", sa.Column("subject", sa.Text(), nullable=True))
    op.add_column("interactions", sa.Column("provider_message_id", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("interactions", "provider_message_id")
    op.drop_column("interactions", "subject")

    op.drop_index("ix_templates_category", table_name="templates")
    op.drop_index("ix_templates_language", table_name="templates")

    op.drop_constraint("uq_templates_channel_name_language", "templates", type_="unique")
    op.create_unique_constraint(
        "uq_templates_channel_name",
        "templates",
        ["channel", "name"],
    )

    op.drop_column("templates", "language")
    op.drop_column("templates", "category")

    op.drop_column("customers", "language")
    op.drop_column("customers", "can_contact")

    # Safe enum drop
    op.execute("DROP TYPE IF EXISTS template_category;")
