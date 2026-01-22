from __future__ import annotations

from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class InteractionCreate(BaseModel):
    channel: str
    direction: str
    content: Optional[str] = None
    occurred_at: datetime | None = None 


class InteractionOut(BaseModel):
    id: UUID
    customer_id: UUID
    owner_user_id: UUID
    channel: str
    direction: str
    occurred_at: datetime
    content: Optional[str] = None

    class Config:
        from_attributes = True
