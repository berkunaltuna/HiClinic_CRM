"""Patient portal access for photo requests.

There is no patient login in the CRM, so access is a per-request link:
- the link token is 256 bits of randomness; only its SHA-256 is stored;
- links expire, can be revoked, and are limited to a number of uses;
- opening a link exchanges it for a short-lived session JWT that is signed with a
  key derived for the portal only and carries its own audience, so it can never be
  used as (or confused with) a staff token, and is bound to one request and link;
- failed exchanges are rate-limited per client IP.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import PhotoAccessLink, PhotoRequest
from app.db.session import get_db

TOKEN_PREFIX = "pr_"
_TOKEN_RE = re.compile(r"^pr_[A-Za-z0-9_-]{43}$")
PORTAL_AUDIENCE = "hiclinic-patient-photo-portal"
PORTAL_TOKEN_TYPE = "photo_portal"

# Requests in these states accept new links and uploads.
UPLOADABLE_STATUSES = ("requested", "more_photos_needed")


def generate_link_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_well_formed(token: str) -> bool:
    return bool(_TOKEN_RE.match(token or ""))


def _portal_key() -> bytes:
    return hmac.new(settings.jwt_secret_key.encode("utf-8"), b"patient-photo-portal:v1", hashlib.sha256).digest()


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def link_is_usable(link: PhotoAccessLink, at: datetime | None = None) -> bool:
    at = at or now_utc()
    return link.revoked_at is None and link.expires_at > at


def create_session_token(link: PhotoAccessLink) -> tuple[str, datetime]:
    now = now_utc()
    exp = now + timedelta(minutes=settings.photo_portal_session_minutes)
    payload = {
        "typ": PORTAL_TOKEN_TYPE,
        "aud": PORTAL_AUDIENCE,
        "sub": str(link.request_id),
        "lid": str(link.id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, _portal_key(), algorithm="HS256"), exp


class PortalContext:
    def __init__(self, request: PhotoRequest, link: PhotoAccessLink):
        self.request = request
        self.link = link


_bearer = HTTPBearer(auto_error=False)

_INVALID = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This link has expired or is no longer valid")


def get_portal_context(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> PortalContext:
    """Resolve a portal session to exactly one request; re-checks the link on every call."""
    if creds is None:
        raise _INVALID
    try:
        payload = jwt.decode(
            creds.credentials,
            _portal_key(),
            algorithms=["HS256"],
            audience=PORTAL_AUDIENCE,
            options={"require": ["exp", "aud", "sub", "lid", "typ"]},
        )
        if payload.get("typ") != PORTAL_TOKEN_TYPE:
            raise ValueError("wrong token type")
        request_id = UUID(payload["sub"])
        link_id = UUID(payload["lid"])
    except Exception:
        raise _INVALID
    link = db.get(PhotoAccessLink, link_id)
    if link is None or link.request_id != request_id or not link_is_usable(link):
        raise _INVALID
    req = db.get(PhotoRequest, request_id)
    if req is None or req.status in ("withdrawn", "closed"):
        raise _INVALID
    return PortalContext(req, link)


# --- Brute-force protection ----------------------------------------------------


class FailedAttemptLimiter:
    """In-process sliding window of failed link exchanges per client.

    The API runs as a single uvicorn process, so in-memory state is sufficient; with
    several workers each would keep its own window (documented).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def _window(self) -> float:
        return settings.photo_portal_lockout_minutes * 60.0

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self._window():
            q.popleft()
        return q

    def is_locked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= settings.photo_portal_max_failed_attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)
            if len(self._hits) > 10_000:  # bound memory under a spray of IPs
                for k in list(self._hits)[:5_000]:
                    self._hits.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


failed_attempts = FailedAttemptLimiter()


def client_key(request: Request) -> str:
    if settings.photo_portal_trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
