from __future__ import annotations

import uuid
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = sa.Column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    email = sa.Column(sa.String(320), unique=True, nullable=False)
    password_hash = sa.Column(sa.String(255), nullable=False)
    role = sa.Column(sa.String(20), nullable=False, server_default="user")

    created_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    customers = relationship("Customer", back_populates="owner")


class Customer(Base):
    __tablename__ = "customers"

    id = sa.Column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    owner_user_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )

    name = sa.Column(sa.String(200), nullable=False)
    email = sa.Column(sa.String(320))
    phone = sa.Column(sa.String(50))
    company = sa.Column(sa.String(200))
    next_follow_up_at = sa.Column(sa.DateTime(timezone=True))
    can_contact = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text('true'))
    language = sa.Column(sa.String(10))

    created_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    owner = relationship("User", back_populates="customers")
    deals = relationship("Deal", back_populates="customer", cascade="all, delete-orphan")
    interactions = relationship(
        "Interaction", back_populates="customer", cascade="all, delete-orphan"
    )


class Deal(Base):
    __tablename__ = "deals"

    id = sa.Column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    customer_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("customers.id"),
        nullable=False,
    )
    owner_user_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )

    amount = sa.Column(sa.Numeric(12, 2), nullable=False, server_default="0")
    status = sa.Column(sa.String(20), nullable=False, server_default="open")

    created_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    customer = relationship("Customer", back_populates="deals")


class Interaction(Base):
    __tablename__ = "interactions"

    id = sa.Column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    customer_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("customers.id"),
        nullable=False,
    )
    owner_user_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )

    channel = sa.Column(sa.String(50), nullable=False)
    direction = sa.Column(sa.String(20), nullable=False)
    occurred_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    content = sa.Column(sa.Text)
    subject = sa.Column(sa.Text)
    provider_message_id = sa.Column(sa.String(200))

    created_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    customer = relationship("Customer", back_populates="interactions")

class Template(Base):
    __tablename__ = "templates"

    id = sa.Column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # Phase 2 supports email and whatsapp templates
    template_channel_enum = sa.Enum("email", "whatsapp", name="template_channel")
    channel = sa.Column(template_channel_enum, nullable=False)
    name = sa.Column(sa.String(200), nullable=False)
    subject = sa.Column(sa.String(300))  # email only; whatsapp templates can leave this NULL
    body = sa.Column(sa.Text(), nullable=False)

    template_category_enum = sa.Enum('transactional', 'marketing', name='template_category')
    category = sa.Column(template_category_enum, nullable=False, server_default='transactional')
    # Language tag for multilingual templates. 'und' means default/unspecified.
    language = sa.Column(sa.String(10), nullable=False, server_default='und')

    created_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    __table_args__ = (
        sa.UniqueConstraint('channel', 'name', 'language', name='uq_templates_channel_name_language'),
    )

