from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class TemplatePreviewRequest(BaseModel):
    customer_id: UUID = Field(..., description="Customer used for merge-field rendering")


class TemplatePreviewOut(BaseModel):
    subject: Optional[str]
    body: str


class EmailSendRequest(BaseModel):
    # Either template_id OR template_name must be provided.
    template_id: Optional[UUID] = None
    template_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_one_of(self):
        if not self.template_id and not self.template_name:
            raise ValueError("template_id or template_name is required")
        return self


class EmailSendOut(BaseModel):
    provider_message_id: str
    interaction_id: UUID
