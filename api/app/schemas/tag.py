from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=20)


class TagOut(BaseModel):
    id: UUID
    name: str
    color: str | None = None

    class Config:
        from_attributes = True
