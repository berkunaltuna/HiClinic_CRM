from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=200)
    trigger_event: str = Field(..., max_length=80)
    is_enabled: bool = True

    # Rule definition (kept intentionally simple for Phase 4C)
    conditions: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    trigger_event: str | None = Field(None, max_length=80)
    is_enabled: bool | None = None
    conditions: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None


class WorkflowOut(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    trigger_event: str
    is_enabled: bool
    conditions: dict[str, Any] | None
    actions: list[dict[str, Any]] | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
