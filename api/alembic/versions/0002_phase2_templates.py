"""Phase 2 templates

Revision ID: 0002_phase2
Revises: 0001_phase1
Create Date: 2026-01-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_phase2"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None

# IMPORTANT:
# - create_type=False prevents SQLAlchemy from trying to CREATE TYPE during table creation
# - we create/drop the type explicitly via op.execute() blocks below (idempotently)
template_channel_enum = postgresql.ENUM(
    "email",
    "whatsapp",
    name="template_channel",
    create_type=False,
)

def upgrade() -> None:
    # Idempotent enum creation (safe even if rerun)
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE template_channel AS ENUM ('email', 'whatsapp');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("channel", template_channel_enum, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("channel", "name", name="uq_templates_channel_name"),
    )

    op.create_index("ix_templates_channel", "templates", ["channel"], unique=False)
    op.create_index("ix_templates_name", "templates", ["name"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_templates_name", table_name="templates")
    op.drop_index("ix_templates_channel", table_name="templates")
    op.drop_table("templates")

    # Safe enum drop
    op.execute("DROP TYPE IF EXISTS template_channel;")
