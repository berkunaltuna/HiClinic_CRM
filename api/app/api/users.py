from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import require_admin
from app.auth.security import hash_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_ROLES = {"admin", "manager", "coordinator", "viewer", "user", "doctor"}


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
    if payload.role is not None:
        role = payload.role.lower().strip()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = role
    db.add(user)
    record_audit(db, actor=admin, action="user.updated", entity_type="user", entity_id=user.id, before=before, after={"role": str(user.role)})
    db.commit()
    db.refresh(user)
    return user
