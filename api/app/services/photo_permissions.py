"""Role permissions for patient photo requests.

This table is the single source of truth (documented in docs/patient-photos.md).
Every staff endpoint checks it on the backend; the frontend only mirrors it.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import settings
from app.db.models import Customer, User

# Roles an admin has to assign explicitly. The default "user" role is excluded on
# purpose: it is what any account starts with, so it must never reach clinical data.
STAFF_WRITERS = frozenset({"admin", "manager", "coordinator", "doctor"})

PERMISSIONS: dict[str, frozenset[str]] = {
    # Request list + status/history (no photos, notes or assessments).
    "photo_request.view_summary": STAFF_WRITERS | {"viewer", "user"},
    "photo_request.create": STAFF_WRITERS,
    # Issue a new portal link or revoke one.
    "photo_request.manage_links": STAFF_WRITERS,
    # in_review, closed, withdrawn.
    "photo_request.manage_status": STAFF_WRITERS,
    "photo.view": STAFF_WRITERS,
    # Hide a photo (soft delete; bytes and metadata are retained).
    "photo.hide": frozenset({"admin", "manager"}),
    "note.view": STAFF_WRITERS,
    "note.write": STAFF_WRITERS,
    "assessment.view": STAFF_WRITERS,
    # Clinical decisions are doctor-only: writing assessments, marking reviewed,
    # and asking the patient for more photos.
    "assessment.write": frozenset({"doctor"}),
    "photo_request.mark_reviewed": frozenset({"doctor"}),
    "photo_request.request_more": frozenset({"doctor"}),
}

# Roles that review across every patient, even when SHARE_CUSTOMERS_ACROSS_USERS is off.
CROSS_OWNER_ROLES = frozenset({"doctor"})


def role_of(user: User) -> str:
    role = getattr(user, "role", None) or "user"
    return str(getattr(role, "value", role))


def has_permission(user: User, permission: str) -> bool:
    return role_of(user) in PERMISSIONS[permission]


def require_permission(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not allow this action")


def sees_all_customers(user: User) -> bool:
    return settings.share_customers_across_users or role_of(user) in CROSS_OWNER_ROLES


def can_access_customer(user: User, customer: Customer) -> bool:
    return sees_all_customers(user) or customer.owner_user_id == user.id


def permissions_for(user: User) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(user, p))
