from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.deal import DealOut


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None

    # Phase 3 additions
    can_contact: bool = True
    language: str | None = Field(default=None, max_length=10)

    lead_source: str | None = Field(default=None, max_length=120)
    form_id: str | None = Field(default=None, max_length=120)
    form_name: str | None = Field(default=None, max_length=250)
    campaign_id: str | None = Field(default=None, max_length=120)
    campaign_name: str | None = Field(default=None, max_length=250)
    adset_id: str | None = Field(default=None, max_length=120)
    adset_name: str | None = Field(default=None, max_length=250)
    ad_id: str | None = Field(default=None, max_length=120)
    ad_name: str | None = Field(default=None, max_length=250)


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None

    # Phase 3 additions
    can_contact: bool | None = None
    language: str | None = Field(default=None, max_length=10)

    # Phase 4B
    stage: str | None = Field(default=None, max_length=40)

    lead_source: str | None = Field(default=None, max_length=120)
    form_id: str | None = Field(default=None, max_length=120)
    form_name: str | None = Field(default=None, max_length=250)
    campaign_id: str | None = Field(default=None, max_length=120)
    campaign_name: str | None = Field(default=None, max_length=250)
    adset_id: str | None = Field(default=None, max_length=120)
    adset_name: str | None = Field(default=None, max_length=250)
    ad_id: str | None = Field(default=None, max_length=120)
    ad_name: str | None = Field(default=None, max_length=250)


class CustomerOut(BaseModel):
    id: UUID
    name: str
    email: EmailStr | None
    phone: str | None
    company: str | None
    next_follow_up_at: datetime | None

    # Phase 3 additions
    can_contact: bool
    language: str | None

    # Phase 4B additions
    stage: str
    tag_names: list[str] = []

    lead_source: str | None = None
    form_id: str | None = None
    form_name: str | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    adset_id: str | None = None
    adset_name: str | None = None
    ad_id: str | None = None
    ad_name: str | None = None

    # Latest deal is included so the UI can show lead form answers without
    # making an extra request on the contact list/inbox.
    latest_deal: DealOut | None = None

    class Config:
        from_attributes = True
