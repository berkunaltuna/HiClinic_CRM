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
    """Send an email to a customer.

    Supports two modes:
    1) Template-based: provide template_id OR template_name
    2) Direct send: provide subject + body

    The frontend uses direct send for a simple email composer.
    """

    # Template mode
    template_id: Optional[UUID] = None
    template_name: Optional[str] = None

    # Direct mode
    subject: Optional[str] = None
    body: Optional[str] = None

    @model_validator(mode="after")
    def validate_one_of(self):
        has_template = bool(self.template_id or self.template_name)
        has_direct = bool((self.subject or "").strip()) and bool((self.body or "").strip())

        if not has_template and not has_direct:
            raise ValueError("Either template_id/template_name OR subject+body is required")

        # If both are provided, prefer template to avoid ambiguous behaviour.
        if has_template and has_direct:
            self.subject = None
            self.body = None
        return self


class EmailSendOut(BaseModel):
    provider_message_id: str
    interaction_id: UUID
