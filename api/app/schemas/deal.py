from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DealCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    title: Optional[str] = None
    amount: float = Field(..., validation_alias="value")
    quote_amount: Optional[float] = None
    status: str = "open"
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None
    event_id: Optional[UUID] = None
    lost_reason: Optional[str] = None


class DealUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    amount: Optional[float] = Field(default=None, validation_alias="value")
    quote_amount: Optional[float] = None
    status: Optional[str] = None
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None
    event_id: Optional[UUID] = None
    lost_reason: Optional[str] = None


class DealOut(BaseModel):
    id: UUID
    customer_id: UUID
    owner_user_id: UUID
    amount: float
    quote_amount: Optional[float] = None
    status: str
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None
    event_id: Optional[UUID] = None
    confirmation_sent_at: Optional[datetime] = None
    confirmation_channel: Optional[str] = None
    confirmation_template_id: Optional[UUID] = None
    confirmed_by_user_id: Optional[UUID] = None
    lost_reason: Optional[str] = None

    class Config:
        from_attributes = True
