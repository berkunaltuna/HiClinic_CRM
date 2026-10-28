from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from uuid import UUID
import logging

from app.auth.security import decode_token, is_staff_access_token
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

security_scheme = HTTPBearer(auto_error=False)

# Roles that only use their own interface (doctor / assistant) and the photo and care-team
# routes. They are refused on every general CRM route by get_current_user.
CARE_TEAM_ROLES = frozenset({"doctor", "doctor_assistant"})


def _role(user: User) -> str:
    role = getattr(user, "role", None) or "user"
    return str(getattr(role, "value", role))


def get_authenticated_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db), ) -> User:
    """Any signed-in staff account. Only for routes that check roles/assignments themselves
    (photo requests, care team, /auth/me)."""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated",)
    token = creds.credentials

    try:
        payload = decode_token(token)
        if not is_staff_access_token(payload):
            raise ValueError("Not an access token")
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub")
        try:
            user_id = UUID(sub)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        
    except Exception:
        logger.exception("JWT authentication failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    """General CRM staff. Doctors and assistants are refused here, so every existing CRM
    route (contacts, deals, events, inbox, templates, settings, users, ...) is closed to
    them by default."""
    if _role(user) in CARE_TEAM_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This area is not available for your role")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require an authenticated admin user (Phase 2 templates permissions)."""
    if getattr(user, 'role', None) != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin only')
    return user
