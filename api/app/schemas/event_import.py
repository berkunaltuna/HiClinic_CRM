from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ImportRowOut(BaseModel):
    id: UUID
    row_number: int
    raw_data: dict
    mapped_data: dict | None = None
    status: str
    match_type: str | None = None
    customer_id: UUID | None = None
    appointment_id: UUID | None = None
    reasons: list[str] | None = None

    class Config:
        from_attributes = True


class ImportBatchOut(BaseModel):
    id: UUID
    event_id: UUID | None = None
    event_name_snapshot: str | None = None
    source_filename: str | None = None
    source_format: str
    mapping: dict | None = None
    status: str
    row_count: int
    customers_created: int
    customers_updated: int
    rows_unchanged: int
    duplicates_merged: int
    bookings_created: int
    bookings_updated: int
    rows_flagged: int
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class ImportUploadOut(BaseModel):
    batch_id: UUID
    headers: list[str]
    suggested_mapping: dict[str, str]
    row_count: int
    sample_rows: list[dict]


class ImportMappingIn(BaseModel):
    mapping: dict[str, str]


class ImportResultOut(BaseModel):
    batch: ImportBatchOut
    rows: list[ImportRowOut]
