"""Phase 6: harden delete foreign keys for bulk actions

Revision ID: 0010_phase6_delete_fk_hardening
Revises: 0009_phase6_meta_facebook_leads
Create Date: 2026-04-06
"""

from __future__ import annotations

from alembic import op

revision = "0010_phase6_delete_fk_hardening"
down_revision = "0009_phase6_meta_facebook_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # facebook_lead_events.customer_id -> customers.id : SET NULL
    op.drop_constraint(
        "facebook_lead_events_customer_id_fkey",
        "facebook_lead_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "facebook_lead_events_customer_id_fkey",
        "facebook_lead_events",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # facebook_lead_events.deal_id -> deals.id : SET NULL
    op.drop_constraint(
        "facebook_lead_events_deal_id_fkey",
        "facebook_lead_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "facebook_lead_events_deal_id_fkey",
        "facebook_lead_events",
        "deals",
        ["deal_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # outbound_messages.customer_id -> customers.id : CASCADE
    op.drop_constraint(
        "outbound_messages_customer_id_fkey",
        "outbound_messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "outbound_messages_customer_id_fkey",
        "outbound_messages",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # outbound_messages.template_id -> templates.id : SET NULL
    op.drop_constraint(
        "outbound_messages_template_id_fkey",
        "outbound_messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "outbound_messages_template_id_fkey",
        "outbound_messages",
        "templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # customer_tags.customer_id -> customers.id : CASCADE
    op.drop_constraint(
        "customer_tags_customer_id_fkey",
        "customer_tags",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "customer_tags_customer_id_fkey",
        "customer_tags",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # customer_tags.tag_id -> tags.id : CASCADE
    op.drop_constraint(
        "customer_tags_tag_id_fkey",
        "customer_tags",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "customer_tags_tag_id_fkey",
        "customer_tags",
        "tags",
        ["tag_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "facebook_lead_events_customer_id_fkey",
        "facebook_lead_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "facebook_lead_events_customer_id_fkey",
        "facebook_lead_events",
        "customers",
        ["customer_id"],
        ["id"],
    )

    op.drop_constraint(
        "facebook_lead_events_deal_id_fkey",
        "facebook_lead_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "facebook_lead_events_deal_id_fkey",
        "facebook_lead_events",
        "deals",
        ["deal_id"],
        ["id"],
    )

    op.drop_constraint(
        "outbound_messages_customer_id_fkey",
        "outbound_messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "outbound_messages_customer_id_fkey",
        "outbound_messages",
        "customers",
        ["customer_id"],
        ["id"],
    )

    op.drop_constraint(
        "outbound_messages_template_id_fkey",
        "outbound_messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "outbound_messages_template_id_fkey",
        "outbound_messages",
        "templates",
        ["template_id"],
        ["id"],
    )

    op.drop_constraint(
        "customer_tags_customer_id_fkey",
        "customer_tags",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "customer_tags_customer_id_fkey",
        "customer_tags",
        "customers",
        ["customer_id"],
        ["id"],
    )

    op.drop_constraint(
        "customer_tags_tag_id_fkey",
        "customer_tags",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "customer_tags_tag_id_fkey",
        "customer_tags",
        "tags",
        ["tag_id"],
        ["id"],
    )