from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DealCreate(BaseModel):
    # Allow clients to send either "amount" (preferred) or "value" (legacy/tests)
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    title: Optional[str] = None  # accepted but ignored by DB (no title column)
    amount: float = Field(..., validation_alias="value")
    status: str = "open"
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None


class DealUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    amount: Optional[float] = Field(default=None, validation_alias="value")
    status: Optional[str] = None
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None


class DealOut(BaseModel):
    id: UUID
    customer_id: UUID
    owner_user_id: UUID
    amount: float
    status: str
    treatment_interest: Optional[str] = None
    preferred_consultation_day: Optional[str] = None
    seminar_preference: Optional[str] = None

    class Config:
        from_attributes = True
