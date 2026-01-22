"""Phase 1 core tables

Revision ID: 0001_phase1
Revises:
Create Date: 2026-01-21

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


# Define enums ONCE and reuse them across all columns/tables
user_role_enum = sa.Enum("user", "admin", name="user_role")
deal_status_enum = sa.Enum("open", "won", "lost", name="deal_status")
interaction_channel_enum = sa.Enum("call", "email", "meeting", "whatsapp", name="interaction_channel")
interaction_direction_enum = sa.Enum("inbound", "outbound", name="interaction_direction")


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_enum, nullable=False, server_default="user"),
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
    )

    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_customers_owner_user_id_users",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_customers_owner_user_id", "customers", ["owner_user_id"], unique=False
    )

    # --- deals ---
    op.create_table(
        "deals",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("status", deal_status_enum, nullable=False, server_default="open"),
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
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_deals_customer_id_customers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_deals_owner_user_id_users",
            ondelete="CASCADE",
        ),
    )

    op.create_index("ix_deals_customer_id", "deals", ["customer_id"], unique=False)
    op.create_index("ix_deals_owner_user_id", "deals", ["owner_user_id"], unique=False)

    # --- interactions ---
    op.create_table(
        "interactions",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("channel", interaction_channel_enum, nullable=False),
        sa.Column("direction", interaction_direction_enum, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("content", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_interactions_customer_id_customers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_interactions_owner_user_id_users",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_interactions_customer_id", "interactions", ["customer_id"], unique=False
    )
    op.create_index(
        "ix_interactions_owner_user_id", "interactions", ["owner_user_id"], unique=False
    )


def downgrade() -> None:
    # Drop tables first (they depend on enums)
    op.drop_index("ix_interactions_owner_user_id", table_name="interactions")
    op.drop_index("ix_interactions_customer_id", table_name="interactions")
    op.drop_table("interactions")

    op.drop_index("ix_deals_owner_user_id", table_name="deals")
    op.drop_index("ix_deals_customer_id", table_name="deals")
    op.drop_table("deals")

    op.drop_index("ix_customers_owner_user_id", table_name="customers")
    op.drop_table("customers")

    op.drop_table("users")

    # Then drop enum types (checkfirst makes it safe to rerun)
    bind = op.get_bind()
    interaction_direction_enum.drop(bind, checkfirst=True)
    interaction_channel_enum.drop(bind, checkfirst=True)
    deal_status_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)
