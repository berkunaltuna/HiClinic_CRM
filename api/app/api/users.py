from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import require_admin
from app.auth.security import hash_password
from app.db.models import AssistantDoctorAssignment, DoctorPatientAssignment, User
from app.db.session import get_db
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_ROLES = {"admin", "manager", "coordinator", "viewer", "user", "doctor", "doctor_assistant"}


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> list[UserOut]:
    return db.query(User).order_by(User.created_at.desc()).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    """Admin-created staff account (public registration is closed by default)."""
    email = str(payload.email).strip().lower()
    role = payload.role.lower().strip()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.flush()
    record_audit(db, actor=admin, action="user.created", entity_type="user", entity_id=user.id, after={"email": email, "role": role})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: UUID, payload: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    before = {"role": str(user.role)}
    old_role = str(getattr(user.role, "value", user.role))
    ended: dict[str, int] = {}
    if payload.role is not None:
        role = payload.role.lower().strip()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = role
        # Leaving a care-team role ends its assignments (history is kept), so a former doctor
        # is no longer shown to patients or reachable through old assignments.
        now = datetime.now(tz=timezone.utc)
        if old_role == "doctor" and role != "doctor":
            ended["patients"] = (
                db.query(DoctorPatientAssignment)
                .filter(DoctorPatientAssignment.doctor_user_id == user.id, DoctorPatientAssignment.ended_at.is_(None))
                .update({DoctorPatientAssignment.ended_at: now, DoctorPatientAssignment.ended_by_user_id: admin.id}, synchronize_session=False)
            )
            ended["assistants"] = (
                db.query(AssistantDoctorAssignment)
                .filter(AssistantDoctorAssignment.doctor_user_id == user.id, AssistantDoctorAssignment.ended_at.is_(None))
                .update({AssistantDoctorAssignment.ended_at: now, AssistantDoctorAssignment.ended_by_user_id: admin.id}, synchronize_session=False)
            )
        if old_role == "doctor_assistant" and role != "doctor_assistant":
            ended["doctors"] = (
                db.query(AssistantDoctorAssignment)
                .filter(AssistantDoctorAssignment.assistant_user_id == user.id, AssistantDoctorAssignment.ended_at.is_(None))
                .update({AssistantDoctorAssignment.ended_at: now, AssistantDoctorAssignment.ended_by_user_id: admin.id}, synchronize_session=False)
            )
    db.add(user)
    record_audit(
        db,
        actor=admin,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after={"role": str(user.role)},
        metadata={"ended_assignments": ended} if any(ended.values()) else None,
    )
    db.commit()
    db.refresh(user)
    return user
