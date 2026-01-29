from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None

    # Phase 3 additions
    can_contact: bool = True
    language: str | None = Field(default=None, max_length=10)


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None

    # Phase 3 additions
    can_contact: bool | None = None
    language: str | None = Field(default=None, max_length=10)


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

    class Config:
        from_attributes = True
