from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


TemplateChannel = Literal["email", "whatsapp"]


class TemplateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: TemplateChannel
    name: str = Field(min_length=1, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=300)
    body: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_subject_for_channel(self):
        if self.channel == "email":
            if not self.subject:
                raise ValueError("subject is required for email templates")
        else:
            # whatsapp: subject is not used
            if self.subject:
                raise ValueError("subject must be null/omitted for whatsapp templates")
        return self


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=300)
    body: Optional[str] = Field(default=None, min_length=1)
    channel: Optional[TemplateChannel] = None

    @model_validator(mode="after")
    def validate_subject_for_channel(self):
        # If channel is explicitly provided, enforce its rules.
        if self.channel == "email":
            if self.subject is None:
                # allow partial updates that don't touch subject
                return self
            if self.subject == "":
                raise ValueError("subject cannot be empty for email templates")
        if self.channel == "whatsapp":
            if self.subject:
                raise ValueError("subject must be null/omitted for whatsapp templates")
        return self


class TemplateOut(BaseModel):
    id: UUID
    channel: TemplateChannel
    name: str
    subject: Optional[str]
    body: str

    class Config:
        from_attributes = True
