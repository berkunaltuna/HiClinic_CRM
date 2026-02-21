from __future__ import annotations

import uuid
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from enum import Enum


from app.db.base import Base

class UserRole(str, Enum):
    admin = "admin"
    user = "user"

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
    user_role_enum = sa.Enum(UserRole, name="user_role")
    role = sa.Column(user_role_enum, nullable=False, server_default=UserRole.user.value)


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

    # Phase 4B: simple funnel stage on the customer record.
    stage = sa.Column(sa.String(40), nullable=False, server_default="new")

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

    # Phase 4B tags
    tags = relationship("CustomerTag", back_populates="customer", cascade="all, delete-orphan")

    @property
    def tag_names(self) -> list[str]:
        # Convenience for API schemas.
        return [ct.tag.name for ct in (self.tags or []) if ct.tag is not None]


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
    interaction_channel_enum = sa.Enum(
        "call", "email", "meeting", "whatsapp",
        name="interaction_channel",
    )
    interaction_direction_enum = sa.Enum(
        "inbound", "outbound",
        name="interaction_direction",
    )

    channel = sa.Column(interaction_channel_enum, nullable=False)
    direction = sa.Column(interaction_direction_enum, nullable=False)
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
    # Optional provider-side template identifier (e.g. Twilio Content SID for WhatsApp)
    provider_template_id = sa.Column(sa.String(120))

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



class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

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

    customer_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("customers.id"),
        nullable=False,
    )

    # Supported channels are expanded in later phases.
    channel = sa.Column(sa.String(20), nullable=False)  # e.g. 'whatsapp', 'email', 'sms'

    # queue status: queued -> sending -> sent | failed
    status = sa.Column(sa.String(20), nullable=False, server_default="queued")

    # If set, the worker can send using provider templates (e.g. Twilio WhatsApp Content SID)
    template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id"))

    # Optional free-form body (e.g. WhatsApp session message)
    body = sa.Column(sa.Text())

    # Provider-specific variables for templates (stored as JSON)
    variables = sa.Column(sa.JSON())

    # Optional scheduling: worker should only send after this time (UTC).
    not_before_at = sa.Column(sa.DateTime(timezone=True))

    # Phase 4C: allow queued messages to be cancelled when an inbound reply arrives.
    cancel_on_inbound = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    cancelled_at = sa.Column(sa.DateTime(timezone=True))

    provider_message_id = sa.Column(sa.String(200))
    last_error = sa.Column(sa.Text())
    retry_count = sa.Column(sa.Integer(), nullable=False, server_default="0")

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


class Workflow(Base):
    """Simple automation rules (Phase 4C).

    A workflow listens for a trigger event (e.g. 'message.received') and, when
    conditions match, enqueues actions (e.g. queue an OutboundMessage).
    """

    __tablename__ = "workflows"

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
    trigger_event = sa.Column(sa.String(80), nullable=False)  # e.g. 'message.received'
    is_enabled = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("true"))

    # Minimal JSON-based rule definition
    conditions = sa.Column(sa.JSON())  # e.g. {"channel": "whatsapp", "is_new_customer": true}
    actions = sa.Column(sa.JSON())  # e.g. [{"type":"send_template","template_name":"welcome"}]

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


class Tag(Base):
    """Tag dictionary (Phase 4B)."""

    __tablename__ = "tags"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)
    name = sa.Column(sa.String(80), nullable=False)
    color = sa.Column(sa.String(20))

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("owner_user_id", "name", name="uq_tags_owner_name"),
    )


class CustomerTag(Base):
    """Many-to-many link between customers and tags (Phase 4B)."""

    __tablename__ = "customer_tags"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False)
    tag_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False)

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    customer = relationship("Customer", back_populates="tags")
    tag = relationship("Tag")

    __table_args__ = (
        sa.UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_customer_tag"),
        sa.Index("ix_customer_tags_owner_customer", "owner_user_id", "customer_id"),
    )


class OutcomeType(str, Enum):
    consult_booked = "consult_booked"
    deposit_paid = "deposit_paid"
    treatment_done = "treatment_done"
    lost = "lost"


class OutcomeEvent(Base):
    """Customer outcome events (Phase 5B).

    Stores business outcomes such as consultation booked, deposit paid, etc.
    Used for KPI dashboards and conversion tracking.
    """

    __tablename__ = "outcome_events"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False)

    outcome_type_enum = sa.Enum(
        OutcomeType,
        name="outcome_type",
        create_type=False,  # prevents duplicate enum creation
    )

    type = sa.Column(outcome_type_enum, nullable=False)

    amount = sa.Column(sa.Numeric(12, 2))  # optional: deposit amount / treatment value
    notes = sa.Column(sa.Text())
    # NOTE: "metadata" is a reserved attribute name in SQLAlchemy Declarative.
    # Keep the DB column name as "metadata" (migration already created it),
    # but expose it on the model as "meta".
    meta = sa.Column("metadata", sa.JSON(), nullable=True)


    occurred_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (
        sa.Index("ix_outcome_events_owner_occurred", "owner_user_id", "occurred_at"),
        sa.Index("ix_outcome_events_owner_type", "owner_user_id", "type"),
    )
