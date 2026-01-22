from __future__ import annotations

from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class DealCreate(BaseModel):
    amount: float
    status: str = "open"


class DealUpdate(BaseModel):
    amount: Optional[float] = None
    status: Optional[str] = None


class DealOut(BaseModel):
    id: UUID
    customer_id: UUID
    owner_user_id: UUID
    amount: float
    status: str

    class Config:
        from_attributes = True
