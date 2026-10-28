"""Role permissions and patient access for photo requests, care team and documents.

This is the single source of truth (documented in docs/patient-photos.md). Every route
checks it on the backend; the frontend only mirrors it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AssistantDoctorAssignment, Customer, DoctorPatientAssignment, User

# CRM roles an admin assigns explicitly. The default "user" role is excluded on purpose:
# it is what any account starts with, so it must never reach clinical data.
CRM_STAFF = frozenset({"admin", "manager", "coordinator"})
STAFF_WRITERS = CRM_STAFF | {"doctor"}

PERMISSIONS: dict[str, frozenset[str]] = {
    # Request list + status/history and upload status (no photos, notes or assessments).
    "photo_request.view_summary": STAFF_WRITERS | {"viewer", "user", "doctor_assistant"},
    # Create a request / issue a link / email the patient the link.
    "photo_request.create": STAFF_WRITERS,
    "photo_request.manage_links": STAFF_WRITERS,
    # Title, instructions, linked appointment/enquiry; only before any photo is uploaded.
    "photo_request.edit_details": STAFF_WRITERS,
    # in_review, closed, withdrawn.
    "photo_request.manage_status": STAFF_WRITERS,
    "photo.view": STAFF_WRITERS,
    # Hide a photo (soft delete; bytes and metadata are retained).
    "photo.hide": frozenset({"admin", "manager"}),
    "note.view": STAFF_WRITERS,
    "note.write": STAFF_WRITERS,
    "assessment.view": STAFF_WRITERS,
    # Clinical decisions are doctor-only.
    "assessment.write": frozenset({"doctor"}),
    "photo_request.mark_reviewed": frozenset({"doctor"}),
    "photo_request.request_more": frozenset({"doctor"}),
    # Proforma invoices.
    "proforma.view": CRM_STAFF | {"doctor_assistant"},
    "proforma.upload": CRM_STAFF | {"doctor_assistant"},
    # Care-team administration.
    "care_team.manage": frozenset({"admin"}),
}


def role_of(user: User) -> str:
    role = getattr(user, "role", None) or "user"
    return str(getattr(role, "value", role))


def has_permission(user: User, permission: str) -> bool:
    return role_of(user) in PERMISSIONS[permission]


def require_permission(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not allow this action")


def permissions_for(user: User) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(user, p))


# --- Which patients a user can reach -------------------------------------------------


def assigned_doctor_ids_for_assistant(db: Session, assistant_id: UUID) -> list[UUID]:
    return [
        r[0]
        for r in db.query(AssistantDoctorAssignment.doctor_user_id).filter(
            AssistantDoctorAssignment.assistant_user_id == assistant_id,
            AssistantDoctorAssignment.ended_at.is_(None),
        )
    ]


def customer_scope(db: Session, user: User):
    """A SQL condition on Customer.id limiting rows to what the user may reach, or None for all."""
    role = role_of(user)
    if role == "admin":
        return None
    if role == "doctor":
        return exists(
            select(DoctorPatientAssignment.id).where(
                DoctorPatientAssignment.customer_id == Customer.id,
                DoctorPatientAssignment.doctor_user_id == user.id,
                DoctorPatientAssignment.ended_at.is_(None),
            )
        )
    if role == "doctor_assistant":
        return exists(
            select(DoctorPatientAssignment.id).where(
                DoctorPatientAssignment.customer_id == Customer.id,
                DoctorPatientAssignment.ended_at.is_(None),
                DoctorPatientAssignment.doctor_user_id.in_(
                    select(AssistantDoctorAssignment.doctor_user_id).where(
                        AssistantDoctorAssignment.assistant_user_id == user.id,
                        AssistantDoctorAssignment.ended_at.is_(None),
                    )
                ),
            )
        )
    if settings.share_customers_across_users:
        return None
    return Customer.owner_user_id == user.id


def can_access_customer(db: Session, user: User, customer: Customer) -> bool:
    scope = customer_scope(db, user)
    if scope is None:
        return True
    return db.query(Customer.id).filter(Customer.id == customer.id, scope).first() is not None


def active_doctor_assignment(db: Session, customer_id: UUID) -> DoctorPatientAssignment | None:
    return (
        db.query(DoctorPatientAssignment)
        .filter(DoctorPatientAssignment.customer_id == customer_id, DoctorPatientAssignment.ended_at.is_(None))
        .first()
    )
