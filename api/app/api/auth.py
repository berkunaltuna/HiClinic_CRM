from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, decode_token, hash_password, verify_password
from app.core.config import settings
from app.db.session import get_db
from app.schemas.auth import ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, RegisterRequest, ResetPasswordRequest, TokenResponse, MeOut
from app.auth.deps import get_current_user
from app.db.models import User, UserRole
from app.services.email_provider import get_email_provider
import jwt
from datetime import datetime, timedelta, timezone
from uuid import UUID


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(id=str(user.id), email=user.email, role=str(getattr(user, "role", "user")))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email_norm = payload.email.strip().lower()
    existing = db.query(User).filter(User.email == email_norm).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = UserRole.admin if email_norm in settings.admin_emails else UserRole.user
    user = User(email=email_norm, password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email_norm = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # If an existing user is now listed as an admin in env/config, upgrade role.
    if email_norm in settings.admin_emails and getattr(user, "role", None) != UserRole.admin:
        user.role = UserRole.admin
        db.add(user)
        db.commit()

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


def _password_reset_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "purpose": "password_reset",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=45)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> ForgotPasswordResponse:
    # Always return a generic success message to avoid exposing registered emails.
    email_norm = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    generic = "If this email exists in the CRM, a password reset link has been sent."
    if user is None:
        return ForgotPasswordResponse(message=generic)

    token = _password_reset_token(user)
    reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
    try:
        provider = get_email_provider(
            provider=settings.email_provider,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_username=settings.smtp_username,
            smtp_password=settings.smtp_password,
            smtp_from_email=settings.smtp_from_email,
            smtp_from_name=settings.smtp_from_name,
            smtp_use_starttls=settings.smtp_use_starttls,
        )
        provider.send_email(
            to_email=user.email,
            subject="Reset your HiClinic CRM password",
            body=f"<p>Use this link to reset your password:</p><p><a href='{reset_url}'>{reset_url}</a></p><p>This link expires in 45 minutes.</p>",
        )
    except Exception:
        # Keep the endpoint safe for production. In fake/dev mode, return the URL so local testing still works.
        if settings.email_provider == "fake":
            return ForgotPasswordResponse(message=generic, reset_url=reset_url)
        return ForgotPasswordResponse(message=generic)
    return ForgotPasswordResponse(message=generic, reset_url=reset_url if settings.email_provider == "fake" else None)


@router.post("/reset-password", response_model=ForgotPasswordResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> ForgotPasswordResponse:
    try:
        decoded = decode_token(payload.token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if decoded.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset link")
    user_id = decoded.get("sub")
    user = db.get(User, UUID(str(user_id)))
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid reset link")
    user.password_hash = hash_password(payload.password)
    db.add(user)
    db.commit()
    return ForgotPasswordResponse(message="Password reset successfully. You can now sign in.")
