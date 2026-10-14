from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

AutomationKey = Literal["appointment_confirmation", "lead_followup"]


class ClinicSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    clinic_name: str
    contact_phone: str | None = None
    contact_email: str | None = None
    updated_at: datetime | None = None


class ClinicSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinic_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    contact_email: EmailStr | None = None


class MessagingAutomationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: AutomationKey
    is_enabled: bool
    email_enabled: bool
    whatsapp_enabled: bool
    email_template_id: UUID | None = None
    whatsapp_template_id: UUID | None = None
    send_updates: bool
    update_email_template_id: UUID | None = None
    update_whatsapp_template_id: UUID | None = None
    delay_minutes: int
    max_per_run: int | None = None
    active_since: datetime | None = None
    updated_at: datetime | None = None
    supported_fields: list[str] = []
    warnings: list[str] = []


class MessagingAutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool | None = None
    email_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    email_template_id: UUID | None = None
    whatsapp_template_id: UUID | None = None
    send_updates: bool | None = None
    update_email_template_id: UUID | None = None
    update_whatsapp_template_id: UUID | None = None
    delay_minutes: int | None = None
    # null = send to everyone due in one check.
    max_per_run: int | None = Field(default=None, ge=1, le=100)


class AutomationsOverview(BaseModel):
    clinic: ClinicSettingsOut
    automations: list[MessagingAutomationOut]
    warnings: list[str] = []


class AutomationSendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    automation_key: str
    kind: str
    customer_id: UUID
    customer_name: str | None = None
    appointment_id: UUID | None = None
    revision: int
    channel: str | None = None
    status: str
    reason: str | None = None
    slot_starts_at: datetime | None = None
    slot_ends_at: datetime | None = None
    template_id: UUID | None = None
    rendered_subject: str | None = None
    rendered_body: str | None = None
    outbound_message_id: UUID | None = None
    attempted_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
