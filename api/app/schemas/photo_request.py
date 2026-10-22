from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PhotoRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=4000)
    appointment_id: UUID | None = None
    deal_id: UUID | None = None


class LinkOption(BaseModel):
    id: UUID
    label: str


class PhotoLinkOptionsOut(BaseModel):
    appointments: list[LinkOption]
    deals: list[LinkOption]


class PhotoRequestOut(BaseModel):
    id: UUID
    customer_id: UUID
    appointment_id: UUID | None = None
    deal_id: UUID | None = None
    title: str
    instructions: str | None = None
    patient_message: str | None = None
    status: str
    upload_round: int
    consent_version: str | None = None
    consent_accepted_at: datetime | None = None
    consent_status: str
    submitted_at: datetime | None = None
    closed_at: datetime | None = None
    created_by_email: str | None = None
    photo_count: int = 0
    created_at: datetime
    updated_at: datetime


class PhotoAccessLinkOut(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    max_uses: int
    use_count: int
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    active: bool

    class Config:
        from_attributes = True


class IssuedLinkOut(BaseModel):
    """Returned once when a link is issued; the token itself is never stored or shown again."""

    request: PhotoRequestOut
    link: PhotoAccessLinkOut
    portal_url: str


class PatientPhotoOut(BaseModel):
    id: UUID
    original_filename: str | None = None
    content_type: str
    size_bytes: int
    upload_round: int
    uploaded_at: datetime
    deleted_at: datetime | None = None
    delete_reason: str | None = None

    class Config:
        from_attributes = True


class EntryRevisionOut(BaseModel):
    version: int
    body: str
    editor_email: str | None = None
    editor_role: str
    created_at: datetime

    class Config:
        from_attributes = True


class EntryOut(BaseModel):
    id: UUID
    author_user_id: UUID | None = None
    author_email: str | None = None
    author_role: str
    body: str
    version: int
    created_at: datetime
    updated_at: datetime
    revisions: list[EntryRevisionOut] = []


class StatusEventOut(BaseModel):
    from_status: str | None = None
    to_status: str
    actor_type: str
    actor_email: str | None = None
    actor_role: str | None = None
    reason: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class PhotoRequestDetailOut(BaseModel):
    request: PhotoRequestOut
    customer_name: str
    # What the caller's role may do (mirrors the backend checks for the UI).
    permissions: list[str]
    photos: list[PatientPhotoOut] | None = None
    notes: list[EntryOut] | None = None
    assessments: list[EntryOut] | None = None
    links: list[PhotoAccessLinkOut]
    history: list[StatusEventOut]


class PhotoRequestQueueItem(PhotoRequestOut):
    customer_name: str


class StatusChangeIn(BaseModel):
    status: Literal["in_review", "more_photos_needed", "reviewed", "closed", "withdrawn"]
    # Internal reason, kept in the status history.
    reason: str | None = Field(default=None, max_length=2000)
    # Shown to the patient; required for more_photos_needed.
    patient_message: str | None = Field(default=None, max_length=2000)


class EntryIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class LinkRevokeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class PhotoHideIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


# --- Patient portal -----------------------------------------------------------


class PortalSessionIn(BaseModel):
    token: str = Field(max_length=200)


class PortalSessionOut(BaseModel):
    session_token: str
    expires_at: datetime


class PortalPhotoOut(BaseModel):
    id: UUID
    original_filename: str | None = None
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class PortalConsentOut(BaseModel):
    version: str
    text: str
    accepted: bool
    accepted_at: datetime | None = None


class PortalLimitsOut(BaseModel):
    max_file_size_bytes: int
    max_files: int
    allowed_extensions: list[str]
    allowed_mime_types: list[str]


class PortalRequestOut(BaseModel):
    """Everything the patient may see. Deliberately has no notes, assessments or staff data."""

    title: str
    instructions: str | None = None
    patient_message: str | None = None
    status: str
    patient_first_name: str
    reviewer: str
    can_upload: bool
    consent: PortalConsentOut
    limits: PortalLimitsOut
    photos: list[PortalPhotoOut]
    submitted_at: datetime | None = None
    created_at: datetime


class PortalConsentIn(BaseModel):
    version: str = Field(max_length=40)
    accepted: Literal[True]
