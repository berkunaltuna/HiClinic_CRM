from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

from typing import Optional
from uuid import UUID


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    next_follow_up_at: datetime | None = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    email: EmailStr | None
    phone: str | None
    company: str | None
    next_follow_up_at: datetime | None

    class Config:
        from_attributes = True
