from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EventDayIn(BaseModel):
    day: date
    start_time: time = time(9, 0)
    end_time: time = time(17, 0)
    slot_minutes: int = Field(default=30, ge=5, le=240)
    break_start_time: time | None = None
    break_end_time: time | None = None
    label: str | None = None


class EventDayOut(EventDayIn):
    id: UUID
    event_id: UUID

    class Config:
        from_attributes = True


class EventCreate(BaseModel):
    name: str
    location: str | None = None
    description: str | None = None
    starts_on: date
    ends_on: date
    default_slot_minutes: int = Field(default=30, ge=5, le=240)
    slot_capacity: int = Field(default=1, ge=1, le=50)
    is_active: bool = True
    days: list[EventDayIn] = []

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on must be after starts_on")
        return self


class EventUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    description: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    default_slot_minutes: int | None = Field(default=None, ge=5, le=240)
    slot_capacity: int | None = Field(default=None, ge=1, le=50)
    is_active: bool | None = None


class EventOut(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    location: str | None = None
    description: str | None = None
    starts_on: date
    ends_on: date
    default_slot_minutes: int
    slot_capacity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    days: list[EventDayOut] = []

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    customer_id: UUID
    deal_id: UUID | None = None
    assigned_user_id: UUID | None = None
    starts_at: datetime
    ends_at: datetime
    appointment_type: str = "consultation"
    status: str = "booked"
    notes: str | None = None


class AppointmentUpdate(BaseModel):
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    assigned_user_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    appointment_type: str | None = None
    status: str | None = None
    notes: str | None = None


class AppointmentOut(BaseModel):
    id: UUID
    event_id: UUID
    customer_id: UUID
    deal_id: UUID | None = None
    assigned_user_id: UUID | None = None
    starts_at: datetime
    ends_at: datetime
    appointment_type: str
    status: str
    notes: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    deal_treatment_interest: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
