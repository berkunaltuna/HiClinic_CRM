from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.deal import DealOut


class InboxCustomerOut(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    stage: str
    tags: list[str] = Field(default_factory=list)
    next_follow_up_at: datetime | None = None
    created_at: datetime

    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    last_activity_at: datetime | None = None
    last_activity_direction: str | None = None
    bucket: str
    latest_deal: DealOut | None = None
    owner_email: str | None = None

    lead_source: str | None = None
    form_id: str | None = None
    form_name: str | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    adset_id: str | None = None
    adset_name: str | None = None
    ad_id: str | None = None
    ad_name: str | None = None


class ThreadItem(BaseModel):
    kind: str
    id: UUID
    direction: str
    channel: str
    occurred_at: datetime
    content: str | None = None
    subject: str | None = None
    status: str | None = None
    template_id: UUID | None = None


class SetStageIn(BaseModel):
    stage: str = Field(min_length=1, max_length=40)
    lost_reason: str | None = Field(default=None, max_length=200)


class SetFollowUpIn(BaseModel):
    next_follow_up_at: datetime | None = None
    minutes_from_now: int | None = Field(default=None, ge=1, le=60 * 24 * 30)


class TagActionIn(BaseModel):
    tag: str = Field(min_length=1, max_length=80)


class SendTextIn(BaseModel):
    body: str = Field(min_length=1)
    channel: str = "whatsapp"
    delay_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    cancel_on_inbound: bool = False
    mark_confirmation: bool = False


class SendTemplateIn(BaseModel):
    template_id: UUID
    channel: str = "whatsapp"
    variables: dict | None = None
    delay_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    cancel_on_inbound: bool = False
    mark_confirmation: bool = False


class MarkConfirmedIn(BaseModel):
    channel: str = Field(default="manual", max_length=40)
