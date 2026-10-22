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


# Token type of staff access tokens. Other tokens signed with JWT_SECRET_KEY
# (e.g. password reset links, which carry `purpose`) must never authenticate a
# staff session; `get_current_user` checks this claim.
ACCESS_TOKEN_TYPE = "access"

# Claim set of access tokens issued before `typ` was added. See
# `is_staff_access_token`.
_LEGACY_ACCESS_TOKEN_CLAIMS = frozenset({"sub", "iat", "exp"})


def create_access_token(subject: str) -> str:
    """Create a signed JWT access token.

    `subject` is typically the user id as a string.
    """
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_access_token_exp_minutes)
    payload = {
        "sub": str(subject),
        "typ": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def is_staff_access_token(payload: dict) -> bool:
    """Whether a decoded JWT is a staff access token.

    New tokens carry `typ: "access"` and no `purpose`. Tokens issued before
    `typ` existed are accepted only if their claims are exactly sub/iat/exp,
    the shape `create_access_token` used to produce; anything else without
    `typ` (password reset tokens, future token kinds) is rejected. Legacy
    tokens expire within JWT_ACCESS_TOKEN_EXP_MINUTES of deploying this
    change, after which the legacy branch can be removed.
    """
    if "purpose" in payload:
        return False
    if "typ" in payload:
        return payload["typ"] == ACCESS_TOKEN_TYPE
    return set(payload) == _LEGACY_ACCESS_TOKEN_CLAIMS
