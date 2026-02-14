from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Dict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


OutboundChannel = Literal["whatsapp", "sms", "email"]
OutboundStatus = Literal["queued", "sending", "sent", "failed"]


class OutboundMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    channel: OutboundChannel = "whatsapp"

    # Either provide a template_id OR a body (or both, but template takes precedence in the worker).
    template_id: Optional[UUID] = None
    body: Optional[str] = Field(default=None, max_length=4000)

    # Provider-specific variables (e.g. Twilio content_variables: {"1": "02/15", "2": "3pm"})
    variables: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_payload(self):
        if self.template_id is None and (self.body is None or not self.body.strip()):
            raise ValueError("Either template_id or body is required")
        if self.body is not None and not self.body.strip():
            self.body = None
        return self


class OutboundMessageOut(BaseModel):
    id: UUID
    customer_id: UUID
    channel: OutboundChannel
    status: OutboundStatus
    template_id: Optional[UUID] = None
    body: Optional[str] = None
    variables: Optional[dict] = None
    provider_message_id: Optional[str] = None
    last_error: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
