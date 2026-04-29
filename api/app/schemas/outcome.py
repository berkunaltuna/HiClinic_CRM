from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class OutcomeEventCreate(BaseModel):
    customer_id: UUID
    type: str = Field(description="consult_booked | deposit_paid | treatment_done | lost")
    amount: Decimal | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    occurred_at: datetime | None = None


class OutcomeEventOut(BaseModel):
    id: UUID
    customer_id: UUID
    type: str
    amount: Decimal | None = None
    notes: str | None = None
    # Model attribute is "meta" (because SQLAlchemy reserves "metadata"),
    # but API field remains "metadata".
    metadata: dict[str, Any] | None = Field(default=None, alias="meta")
    occurred_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class KPIResponse(BaseModel):
    start: datetime
    end: datetime
    leads_created: int
    outbound_sent: int
    inbound_received: int
    median_first_response_seconds: float | None = None
    outcomes: dict[str, int]
    conversion_rates: dict[str, float]


class LeadsByDayPoint(BaseModel):
    date: str  # YYYY-MM-DD
    leads: int


class TemplateEffectivenessRow(BaseModel):
    template_id: UUID
    template_name: str
    sent: int
    replied_within_7d: int
    reply_rate_7d: float
