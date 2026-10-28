from __future__ import annotations

import uuid
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from enum import Enum


from app.db.base import Base

class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    coordinator = "coordinator"
    viewer = "viewer"
    user = "user"
    # Clinical reviewer: the only role that may write clinical photo assessments.
    # Doctors only reach the doctor interface and their assigned patients.
    doctor = "doctor"
    # Works for one or more doctors: sees those doctors' patients' request status and
    # manages proforma invoices. No clinical content, no CRM pages.
    doctor_assistant = "doctor_assistant"

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

    # Contact details left on a lead form count as permission to email/WhatsApp;
    # can_contact=false is the opt-out (e.g. the patient replied STOP).
    # consent_source holds staff's note on the opt-out; consent_updated_at when it changed.
    consent_source = sa.Column(sa.String(200))
    consent_updated_at = sa.Column(sa.DateTime(timezone=True))

    # Lead attribution fields, populated from Make/Meta where available.
    lead_source = sa.Column(sa.String(120))
    form_id = sa.Column(sa.String(120))
    form_name = sa.Column(sa.String(250))
    campaign_id = sa.Column(sa.String(120))
    campaign_name = sa.Column(sa.String(250))
    adset_id = sa.Column(sa.String(120))
    adset_name = sa.Column(sa.String(250))
    ad_id = sa.Column(sa.String(120))
    ad_name = sa.Column(sa.String(250))

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

    @property
    def latest_deal(self):
        deals = list(self.deals or [])
        if not deals:
            return None
        return sorted(deals, key=lambda d: d.created_at or d.id, reverse=True)[0]

class DealStatus(str, Enum):
    open = "open"
    won = "won"
    lost = "lost"

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
    quote_amount = sa.Column(sa.Numeric(12, 2), nullable=True)

    # Lead form answers mapped from Meta/Facebook Lead Ads. Kept on the deal
    # because one customer can enquire about multiple treatments over time.
    treatment_interest = sa.Column(sa.String(200))
    preferred_consultation_day = sa.Column(sa.String(200))
    seminar_preference = sa.Column(sa.String(300))
    event_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    confirmation_sent_at = sa.Column(sa.DateTime(timezone=True))
    confirmation_channel = sa.Column(sa.String(40))
    confirmation_template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    confirmed_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    lost_reason = sa.Column(sa.String(200))

    status = sa.Column(
    sa.Enum(DealStatus, name="deal_status"),
    nullable=False,
    server_default=DealStatus.open.value,)

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
    # When an admin confirmed WhatsApp approved that Content template; cleared when the
    # text or SID changes. Automated WhatsApp messages require it.
    provider_approved_at = sa.Column(sa.DateTime(timezone=True))

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
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Supported channels are expanded in later phases.
    channel = sa.Column(sa.String(20), nullable=False)  # e.g. 'whatsapp', 'email', 'sms'

    # queue status: queued -> sending -> sent | failed
    status = sa.Column(sa.String(20), nullable=False, server_default="queued")

    # If set, the worker can send using provider templates (e.g. Twilio WhatsApp Content SID)
    template_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )

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

    customer = relationship("Customer")
    template = relationship("Template")

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None

    @property
    def template_name(self) -> str | None:
        return self.template.name if self.template is not None else None


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
    customer_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    customer = relationship("Customer", back_populates="tags")
    tag = relationship("Tag")

    __table_args__ = (
        sa.UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_customer_tag"),
        sa.Index("ix_customer_tags_owner_customer", "owner_user_id", "customer_id"),
    )


class FacebookLeadEvent(Base):
    """Tracks ingested Facebook leadgen events to prevent duplicate CRM leads."""

    __tablename__ = "facebook_lead_events"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)

    leadgen_id = sa.Column(sa.String(120), nullable=False, unique=True)
    page_id = sa.Column(sa.String(120))
    form_id = sa.Column(sa.String(120))
    campaign_id = sa.Column(sa.String(120))
    campaign_name = sa.Column(sa.String(250))
    adset_id = sa.Column(sa.String(120))
    adset_name = sa.Column(sa.String(250))
    ad_id = sa.Column(sa.String(120))
    ad_name = sa.Column(sa.String(250))
    form_name = sa.Column(sa.String(250))

    # Which platform delivered this submission ('facebook' | 'google'). Despite
    # the table name, every ad-platform lead submission is recorded here.
    source = sa.Column(sa.String(40), nullable=False, server_default="facebook")
    gclid = sa.Column(sa.String(500))
    is_test = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())

    customer_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    deal_id = sa.Column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )

    raw_payload = sa.Column(sa.JSON(), nullable=True)

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (
        sa.Index("ix_facebook_lead_events_owner_created", "owner_user_id", "created_at"),
    )


class AuditLog(Base):
    """Append-only activity log for CRM actions."""

    __tablename__ = "audit_logs"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    actor_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True)
    actor_email = sa.Column(sa.String(320))
    action = sa.Column(sa.String(100), nullable=False)
    entity_type = sa.Column(sa.String(80), nullable=False)
    entity_id = sa.Column(sa.UUID(as_uuid=True), nullable=True)
    before = sa.Column(sa.JSON(), nullable=True)
    after = sa.Column(sa.JSON(), nullable=True)
    meta = sa.Column("metadata", sa.JSON(), nullable=True)
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    actor = relationship("User")

    __table_args__ = (
        sa.Index("ix_audit_logs_created", "created_at"),
        sa.Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        sa.Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
    )


class Event(Base):
    __tablename__ = "events"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)
    name = sa.Column(sa.String(200), nullable=False)
    location = sa.Column(sa.String(300))
    description = sa.Column(sa.Text())
    starts_on = sa.Column(sa.Date(), nullable=False)
    ends_on = sa.Column(sa.Date(), nullable=False)
    default_slot_minutes = sa.Column(sa.Integer(), nullable=False, server_default="30")
    slot_capacity = sa.Column(sa.Integer(), nullable=False, server_default="1")
    is_active = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("true"))
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    days = relationship("EventDay", back_populates="event", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="event", cascade="all, delete-orphan")


class EventDay(Base):
    __tablename__ = "event_days"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    event_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    day = sa.Column(sa.Date(), nullable=False)
    start_time = sa.Column(sa.Time(), nullable=False)
    end_time = sa.Column(sa.Time(), nullable=False)
    slot_minutes = sa.Column(sa.Integer(), nullable=False, server_default="30")
    break_start_time = sa.Column(sa.Time())
    break_end_time = sa.Column(sa.Time())
    label = sa.Column(sa.String(120))

    event = relationship("Event", back_populates="days")

    __table_args__ = (sa.UniqueConstraint("event_id", "day", name="uq_event_days_event_day"),)


class Appointment(Base):
    __tablename__ = "appointments"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    event_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    deal_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    assigned_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True)
    starts_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    ends_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    appointment_type = sa.Column(sa.String(80), nullable=False, server_default="consultation")
    status = sa.Column(sa.String(40), nullable=False, server_default="booked")
    notes = sa.Column(sa.Text())
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    event = relationship("Event", back_populates="appointments")
    customer = relationship("Customer")
    deal = relationship("Deal")
    assigned_user = relationship("User")

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None

    @property
    def customer_phone(self) -> str | None:
        return self.customer.phone if self.customer is not None else None

    @property
    def deal_treatment_interest(self) -> str | None:
        return self.deal.treatment_interest if self.deal is not None else None

    __table_args__ = (
        sa.Index("ix_appointments_event_starts", "event_id", "starts_at"),
        sa.Index("ix_appointments_customer", "customer_id"),
    )


class ImportBatch(Base):
    """A single Excel/CSV event-booking import run (upload -> preview -> commit)."""

    __tablename__ = "import_batches"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    owner_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)
    event_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    event_name_snapshot = sa.Column(sa.String(200))

    source_filename = sa.Column(sa.String(300))
    source_format = sa.Column(sa.String(10), nullable=False)  # 'xlsx' | 'csv'
    mapping = sa.Column(sa.JSON(), nullable=True)

    status = sa.Column(sa.String(20), nullable=False, server_default="uploaded")
    committing_started_at = sa.Column(sa.DateTime(timezone=True), nullable=True)

    row_count = sa.Column(sa.Integer(), nullable=False, server_default="0")
    customers_created = sa.Column(sa.Integer(), nullable=False, server_default="0")
    customers_updated = sa.Column(sa.Integer(), nullable=False, server_default="0")
    rows_unchanged = sa.Column(sa.Integer(), nullable=False, server_default="0")
    duplicates_merged = sa.Column(sa.Integer(), nullable=False, server_default="0")
    bookings_created = sa.Column(sa.Integer(), nullable=False, server_default="0")
    bookings_updated = sa.Column(sa.Integer(), nullable=False, server_default="0")
    rows_flagged = sa.Column(sa.Integer(), nullable=False, server_default="0")

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    completed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)

    rows = relationship("ImportRow", back_populates="batch", cascade="all, delete-orphan", order_by="ImportRow.row_number")


class ImportRow(Base):
    """One spreadsheet row of an ImportBatch, with its resolved outcome."""

    __tablename__ = "import_rows"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    batch_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    row_number = sa.Column(sa.Integer(), nullable=False)

    raw_data = sa.Column(sa.JSON(), nullable=False)
    mapped_data = sa.Column(sa.JSON(), nullable=True)

    status = sa.Column(sa.String(20), nullable=False, server_default="pending")
    match_type = sa.Column(sa.String(20), nullable=True)

    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    appointment_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)

    reasons = sa.Column(sa.JSON(), nullable=True)

    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    batch = relationship("ImportBatch", back_populates="rows")

    __table_args__ = (
        sa.UniqueConstraint("batch_id", "row_number", name="uq_import_rows_batch_row"),
        sa.Index("ix_import_rows_batch_status", "batch_id", "status"),
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
    # Migration allows customer_id to be nullable (and also supports deal_id).
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True)
    deal_id = sa.Column(sa.UUID(as_uuid=True), nullable=True)

    outcome_type_enum = sa.Enum(
        OutcomeType,
        name="outcome_type",
        create_type=False,  # prevents duplicate enum creation
    )

    # DB column name is "outcome" (see migration 0007), but historically the
    # code/schema used the concept "type". Map the model attribute "type" to
    # the underlying "outcome" column to avoid column-name mismatches.
    type = sa.Column("outcome", outcome_type_enum, nullable=False)

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
        # Keep the index name compatible with the migration (owner_outcome).
        sa.Index("ix_outcome_events_owner_outcome", "owner_user_id", "outcome"),
    )


class ClinicSettings(Base):
    """Single-row clinic profile used in patient-facing automated messages."""

    __tablename__ = "clinic_settings"

    id = sa.Column(sa.Integer(), primary_key=True, default=1)
    clinic_name = sa.Column(sa.String(200), nullable=False, server_default="Health Clinic")
    contact_phone = sa.Column(sa.String(50))
    contact_email = sa.Column(sa.String(320))
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


class MessagingAutomation(Base):
    """Admin-controlled settings for one built-in messaging automation.

    key is 'appointment_confirmation' or 'lead_followup'. active_since is stamped
    whenever the automation is switched on, so enabling it never back-fills
    messages for bookings or leads that existed while it was off.
    """

    __tablename__ = "messaging_automations"

    key = sa.Column(sa.String(60), primary_key=True)
    is_enabled = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    email_enabled = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    whatsapp_enabled = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    email_template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    whatsapp_template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    # Appointment confirmation only: what to send when a confirmed booking moves slot.
    send_updates = sa.Column(sa.Boolean(), nullable=False, server_default=sa.true())
    update_email_template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    update_whatsapp_template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    # Lead follow-up only.
    delay_minutes = sa.Column(sa.Integer(), nullable=False, server_default="1440")
    # Most patients messaged per automation check (NULL = no limit). Anyone over
    # the limit waits for the next check, roughly a minute later.
    max_per_run = sa.Column(sa.Integer(), nullable=True)
    # True = every message waits as "pending_approval" until a staff member approves it.
    require_approval = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    active_since = sa.Column(sa.DateTime(timezone=True))
    updated_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


class AutomationSend(Base):
    """One decision/attempt by a messaging automation, per channel.

    dedupe_key is unique, so processing the same booking or lead twice can never
    queue a second message. channel is NULL for round-level entries (e.g. a
    booking flagged for staff review before any channel is attempted).
    Channel rows: pending_approval -> queued -> sent | failed, with paused (waiting on a
    staff message), held (temporary staff hold), reapproval (booking changed after approval),
    excluded, skipped, needs_review, cancelled, dismissed.
    Round rows (channel NULL): needs_review, held, released, excluded, skipped, resolved.
    """

    __tablename__ = "automation_sends"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    automation_key = sa.Column(sa.String(60), nullable=False)
    dedupe_key = sa.Column(sa.String(300), nullable=False, unique=True)
    kind = sa.Column(sa.String(30), nullable=False)  # confirmation | update | followup
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    appointment_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    revision = sa.Column(sa.Integer(), nullable=False, server_default="1")
    channel = sa.Column(sa.String(20))
    status = sa.Column(sa.String(20), nullable=False)
    reason = sa.Column(sa.Text())
    slot_starts_at = sa.Column(sa.DateTime(timezone=True))
    slot_ends_at = sa.Column(sa.DateTime(timezone=True))
    template_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    rendered_subject = sa.Column(sa.Text())
    rendered_body = sa.Column(sa.Text())
    # What is handed to the worker: {"template_id", "body", "variables"}, plus for event
    # confirmations the {"booking": {event_date, slot, event_venue}} it was rendered with.
    payload = sa.Column(sa.JSON())
    approved_at = sa.Column(sa.DateTime(timezone=True))
    approved_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    outbound_message_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True)
    attempted_at = sa.Column(sa.DateTime(timezone=True))
    sent_at = sa.Column(sa.DateTime(timezone=True))
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    customer = relationship("Customer")
    outbound_message = relationship("OutboundMessage")

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None

    __table_args__ = (
        sa.Index("ix_automation_sends_key_status", "automation_key", "status"),
        sa.Index("ix_automation_sends_customer", "customer_id"),
        sa.Index("ix_automation_sends_appointment", "appointment_id"),
    )


# --- Patient photo requests -------------------------------------------------
# See docs/patient-photos.md. Photo bytes live in private storage (storage_key);
# only metadata is stored here. Rows are never hard-deleted: requests are
# withdrawn/closed, photos and links are soft-deleted/revoked, and notes and
# assessments keep every prior body in photo_entry_revisions.

PHOTO_REQUEST_STATUSES = (
    "requested",
    "uploaded",
    "in_review",
    "more_photos_needed",
    "reviewed",
    "closed",
    "withdrawn",
)


class PhotoRequest(Base):
    __tablename__ = "photo_requests"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    # RESTRICT: deleting a customer must not silently erase clinical photo history.
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    appointment_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    # The treatment enquiry (deal) the photos relate to, if any.
    deal_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Patient-visible: what the request is for and which photos are needed.
    title = sa.Column(sa.String(200), nullable=False)
    instructions = sa.Column(sa.Text())
    # Patient-visible message set with "more photos needed" (never internal notes).
    patient_message = sa.Column(sa.Text())

    status = sa.Column(sa.String(30), nullable=False, server_default="requested")
    # Increments on each "more photos needed"; photos record the round they belong to.
    upload_round = sa.Column(sa.Integer(), nullable=False, server_default="1")

    consent_version = sa.Column(sa.String(40))
    consent_accepted_at = sa.Column(sa.DateTime(timezone=True))
    consent_link_id = sa.Column(sa.UUID(as_uuid=True), nullable=True)

    submitted_at = sa.Column(sa.DateTime(timezone=True))
    closed_at = sa.Column(sa.DateTime(timezone=True))
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    customer = relationship("Customer")
    appointment = relationship("Appointment")
    deal = relationship("Deal")
    created_by = relationship("User")

    @property
    def consent_status(self) -> str:
        return "accepted" if self.consent_accepted_at is not None else "pending"

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('requested','uploaded','in_review','more_photos_needed','reviewed','closed','withdrawn')",
            name="ck_photo_requests_status",
        ),
        sa.Index("ix_photo_requests_customer", "customer_id", "created_at"),
        sa.Index("ix_photo_requests_status", "status", "updated_at"),
    )


class PhotoRequestDetailChange(Base):
    """One edit of a request's details (title, instructions, linked appointment/enquiry).
    `before`/`after` hold only the fields that changed."""

    __tablename__ = "photo_request_detail_changes"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    changed_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_email = sa.Column(sa.String(320))
    changed_by_role = sa.Column(sa.String(30), nullable=False)
    before = sa.Column(sa.JSON(), nullable=False)
    after = sa.Column(sa.JSON(), nullable=False)
    patient_notified = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (sa.Index("ix_photo_request_detail_changes_request", "request_id", "created_at"),)


class PhotoRequestEmail(Base):
    """One email of a portal link through the outbox. Unique per link, so a retried send
    can never queue a second email for the same link."""

    __tablename__ = "photo_request_emails"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    link_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_access_links.id", ondelete="CASCADE"), nullable=False, unique=True)
    outbound_message_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True)
    to_email = sa.Column(sa.String(320), nullable=False)
    sent_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    outbound_message = relationship("OutboundMessage")
    sent_by = relationship("User")

    __table_args__ = (sa.Index("ix_photo_request_emails_request", "request_id", "created_at"),)


class PhotoAccessLink(Base):
    """A patient portal link for one photo request. Only the token's SHA-256 is stored."""

    __tablename__ = "photo_access_links"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    token_hash = sa.Column(sa.String(64), nullable=False, unique=True)
    created_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    max_uses = sa.Column(sa.Integer(), nullable=False)
    use_count = sa.Column(sa.Integer(), nullable=False, server_default="0")
    last_used_at = sa.Column(sa.DateTime(timezone=True))
    revoked_at = sa.Column(sa.DateTime(timezone=True))
    revoked_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoke_reason = sa.Column(sa.String(200))
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (sa.Index("ix_photo_access_links_request", "request_id"),)


class PatientPhoto(Base):
    __tablename__ = "patient_photos"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    # Random, never derived from patient data or the original filename.
    storage_key = sa.Column(sa.String(200), nullable=False, unique=True)
    # Display metadata only (sanitised); never used for storage paths.
    original_filename = sa.Column(sa.String(255))
    content_type = sa.Column(sa.String(50), nullable=False)
    size_bytes = sa.Column(sa.BigInteger(), nullable=False)
    sha256 = sa.Column(sa.String(64), nullable=False)
    upload_round = sa.Column(sa.Integer(), nullable=False, server_default="1")
    uploaded_via_link_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_access_links.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    # Soft delete: patient removed it before submitting, or staff hid it.
    deleted_at = sa.Column(sa.DateTime(timezone=True))
    deleted_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    delete_reason = sa.Column(sa.String(200))

    __table_args__ = (sa.Index("ix_patient_photos_request", "request_id", "upload_round"),)


class PhotoRequestNote(Base):
    """Internal administrative note. Staff-only; never returned to the patient portal."""

    __tablename__ = "photo_request_notes"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    author_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_email = sa.Column(sa.String(320))
    author_role = sa.Column(sa.String(30), nullable=False)
    body = sa.Column(sa.Text(), nullable=False)
    version = sa.Column(sa.Integer(), nullable=False, server_default="1")
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (sa.Index("ix_photo_request_notes_request", "request_id", "created_at"),)


class PhotoClinicalAssessment(Base):
    """A doctor's clinical assessment. Kept apart from internal notes and patient content."""

    __tablename__ = "photo_clinical_assessments"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    author_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_email = sa.Column(sa.String(320))
    author_role = sa.Column(sa.String(30), nullable=False)
    body = sa.Column(sa.Text(), nullable=False)
    version = sa.Column(sa.Integer(), nullable=False, server_default="1")
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (sa.Index("ix_photo_clinical_assessments_request", "request_id", "created_at"),)


class PhotoEntryRevision(Base):
    """Every version of a note or assessment body, so edits never overwrite history."""

    __tablename__ = "photo_entry_revisions"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    entry_type = sa.Column(sa.String(20), nullable=False)  # note | assessment
    entry_id = sa.Column(sa.UUID(as_uuid=True), nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    version = sa.Column(sa.Integer(), nullable=False)
    body = sa.Column(sa.Text(), nullable=False)
    editor_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    editor_email = sa.Column(sa.String(320))
    editor_role = sa.Column(sa.String(30), nullable=False)
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("entry_type", "entry_id", "version", name="uq_photo_entry_revisions_version"),
        sa.Index("ix_photo_entry_revisions_entry", "entry_type", "entry_id"),
    )


class PhotoRequestStatusEvent(Base):
    """Status history shown on the patient record."""

    __tablename__ = "photo_request_status_events"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    request_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("photo_requests.id", ondelete="CASCADE"), nullable=False)
    from_status = sa.Column(sa.String(30))
    to_status = sa.Column(sa.String(30), nullable=False)
    actor_type = sa.Column(sa.String(20), nullable=False)  # staff | patient
    actor_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email = sa.Column(sa.String(320))
    actor_role = sa.Column(sa.String(30))
    reason = sa.Column(sa.Text())
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (sa.Index("ix_photo_request_status_events_request", "request_id", "created_at"),)


# --- Care team: doctor/assistant assignments, doctor profiles, patient documents ----


class DoctorPatientAssignment(Base):
    """Explicit doctor-to-patient assignment (never inferred). At most one active doctor
    per patient; reassigning ends the old row so history is kept."""

    __tablename__ = "doctor_patient_assignments"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    doctor_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    assigned_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    ended_at = sa.Column(sa.DateTime(timezone=True))
    ended_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    doctor = relationship("User", foreign_keys=[doctor_user_id])

    __table_args__ = (
        sa.Index(
            "uq_doctor_patient_active",
            "customer_id",
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL"),
        ),
        sa.Index("ix_doctor_patient_doctor", "doctor_user_id", "ended_at"),
    )


class AssistantDoctorAssignment(Base):
    """An assistant works for a doctor (admin-managed)."""

    __tablename__ = "assistant_doctor_assignments"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    assistant_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    doctor_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    ended_at = sa.Column(sa.DateTime(timezone=True))
    ended_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        sa.Index(
            "uq_assistant_doctor_active",
            "assistant_user_id",
            "doctor_user_id",
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL"),
        ),
    )


class DoctorProfile(Base):
    """What patients see about their doctor. Admin-managed; every field is optional and
    nothing is shown unless filled in and marked visible."""

    __tablename__ = "doctor_profiles"

    user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name = sa.Column(sa.String(200))
    title = sa.Column(sa.String(200))
    specialty = sa.Column(sa.String(200))
    bio = sa.Column(sa.Text())
    visible_to_patients = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    updated_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


class PatientDocument(Base):
    """A private patient document (currently: proforma invoices). Bytes in private
    storage; replacing a document supersedes it instead of deleting it."""

    __tablename__ = "patient_documents"

    id = sa.Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    customer_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    category = sa.Column(sa.String(30), nullable=False)  # proforma
    storage_key = sa.Column(sa.String(200), nullable=False, unique=True)
    original_filename = sa.Column(sa.String(255))
    content_type = sa.Column(sa.String(50), nullable=False)
    size_bytes = sa.Column(sa.BigInteger(), nullable=False)
    sha256 = sa.Column(sa.String(64), nullable=False)
    uploaded_by_user_id = sa.Column(sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
    superseded_at = sa.Column(sa.DateTime(timezone=True))
    superseded_by_id = sa.Column(sa.UUID(as_uuid=True), nullable=True)

    uploaded_by = relationship("User")

    __table_args__ = (
        sa.CheckConstraint("category IN ('proforma')", name="ck_patient_documents_category"),
        sa.Index("ix_patient_documents_customer", "customer_id", "category", "superseded_at"),
    )
