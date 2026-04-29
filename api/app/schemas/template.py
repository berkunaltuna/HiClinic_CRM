from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


TemplateChannel = Literal["email", "whatsapp"]
TemplateCategory = Literal["transactional", "marketing"]


class TemplateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: TemplateChannel
    name: str = Field(min_length=1, max_length=200)

    # Phase 3 additions
    category: TemplateCategory = "transactional"
    # Language tag for multilingual templates. None means default ('und' in DB).
    language: Optional[str] = Field(default=None, max_length=10)

    subject: Optional[str] = Field(default=None, max_length=300)
    body: str = Field(min_length=1)
    # Optional provider-side template identifier (e.g. Twilio Content SID for WhatsApp)
    provider_template_id: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_template(self):
        # subject rules
        if self.channel == "email":
            if not self.subject:
                raise ValueError("subject is required for email templates")
        else:
            if self.subject:
                raise ValueError("subject must be null/omitted for whatsapp templates")

        # provider template id normalisation
        if self.provider_template_id is not None and not self.provider_template_id.strip():
            self.provider_template_id = None
        if self.provider_template_id is not None:
            self.provider_template_id = self.provider_template_id.strip()

        # language normalisation
        if self.language is not None and not self.language.strip():
            self.language = None
        if self.language is not None:
            self.language = self.language.strip().lower()
        return self


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=300)
    body: Optional[str] = Field(default=None, min_length=1)
    provider_template_id: Optional[str] = Field(default=None, max_length=120)
    channel: Optional[TemplateChannel] = None

    # Phase 3 additions
    category: Optional[TemplateCategory] = None
    language: Optional[str] = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def validate_template(self):
        # If channel is explicitly provided, enforce its rules.
        if self.channel == "whatsapp" and self.subject:
            raise ValueError("subject must be null/omitted for whatsapp templates")
        if self.channel == "email" and self.subject == "":
            raise ValueError("subject cannot be empty for email templates")

        if self.language is not None and not self.language.strip():
            self.language = None
        if self.language is not None:
            self.language = self.language.strip().lower()
        return self


class TemplateOut(BaseModel):
    id: UUID
    channel: TemplateChannel
    name: str
    category: TemplateCategory
    language: Optional[str]
    subject: Optional[str]
    body: str
    provider_template_id: Optional[str] = None

    class Config:
        from_attributes = True
