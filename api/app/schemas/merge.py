from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.schemas.customer import CustomerOut


class MergePreviewIn(BaseModel):
    loser_customer_id: UUID


class FieldConflictOut(BaseModel):
    field: str
    survivor_value: str | None
    loser_value: str | None


class BookingPairOut(BaseModel):
    event_id: str
    event_name: str | None
    survivor_appointment_id: str
    loser_appointment_id: str
    starts_at: str
    kind: str
    detail: dict
    both_active: bool


class MergeAnalysisOut(BaseModel):
    survivor_id: str
    loser_id: str
    conflicts: list[FieldConflictOut]
    identical_bookings: list[BookingPairOut]
    divergent_bookings: list[BookingPairOut]
    capacity_conflicts: list[BookingPairOut]
    fingerprint: str


class MergeCommitIn(BaseModel):
    loser_customer_id: UUID
    confirmed_fingerprint: str


class MergeCommitOut(BaseModel):
    survivor: CustomerOut
    filled_fields: list[str]
    cancelled_duplicate_appointment_ids: list[str] = []
    analysis: MergeAnalysisOut


class MergeDriftOut(BaseModel):
    requires_reconfirmation: bool = True
    analysis: MergeAnalysisOut


class MergeBlockedOut(BaseModel):
    requires_manual_resolution: bool = True
    analysis: MergeAnalysisOut
