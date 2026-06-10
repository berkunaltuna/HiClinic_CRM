from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: UUID | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True
