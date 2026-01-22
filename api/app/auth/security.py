from __future__ import annotations
from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"],deprecated="auto",)

from app.core.config import settings

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    """Create a signed JWT access token.

    `subject` is typically the user id as a string.
    """
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_access_token_exp_minutes)
    payload = {"sub": str(subject), "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
