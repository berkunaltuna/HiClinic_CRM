from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InboxCustomerOut(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    stage: str
    tags: list[str] = Field(default_factory=list)
    next_follow_up_at: datetime | None = None

    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    last_activity_at: datetime | None = None
    last_activity_direction: str | None = None
    bucket: str


class ThreadItem(BaseModel):
    kind: str  # interaction | outbound_message
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


class SendTemplateIn(BaseModel):
    template_id: UUID
    channel: str = "whatsapp"
    variables: dict | None = None
    delay_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    cancel_on_inbound: bool = False
