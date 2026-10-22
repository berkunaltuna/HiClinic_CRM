"""Server-side admin commands. Run inside the API container, e.g.

    docker compose exec api python -m app.cli create-first-admin --email you@clinic.com

Needs shell access to the server, so it is not reachable from the internet.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Callable, TextIO

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db.models import User, UserRole
from app.services.audit import record_audit

MIN_PASSWORD_LENGTH = 8
# Serialises concurrent first-admin attempts (held until the transaction ends).
_FIRST_ADMIN_LOCK_KEY = 7_321_001


class FirstAdminError(Exception):
    pass


def create_first_admin(db: Session, email: str, password: str) -> User:
    """Create the initial admin. Refuses once any admin account exists."""
    try:
        email_norm = validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise FirstAdminError(f"Invalid email: {exc}") from exc
    if len(password) < MIN_PASSWORD_LENGTH:
        raise FirstAdminError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _FIRST_ADMIN_LOCK_KEY})
    if db.query(User.id).filter(User.role == UserRole.admin).first() is not None:
        raise FirstAdminError("An admin account already exists. Create further accounts on the Users page.")
    if db.query(User.id).filter(User.email == email_norm).first() is not None:
        raise FirstAdminError("That email already has an account.")

    user = User(email=email_norm, password_hash=hash_password(password), role=UserRole.admin)
    db.add(user)
    db.flush()
    record_audit(
        db,
        actor=None,
        action="user.first_admin_created",
        entity_type="user",
        entity_id=user.id,
        after={"email": email_norm, "role": "admin"},
        metadata={"via": "cli"},
    )
    db.commit()
    return user


def _read_password(from_stdin: bool, stdin: TextIO) -> str:
    if from_stdin:
        return stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise FirstAdminError("Passwords do not match")
    return first


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    stdin: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-first-admin", help="Create the initial admin (only when no admin exists)")
    p.add_argument("--email", required=True)
    p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin instead of prompting")
    args = parser.parse_args(argv)

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        password = _read_password(args.password_stdin, stdin)
        created_email = create_first_admin(db, args.email, password).email
    except FirstAdminError as exc:
        db.rollback()
        print(f"Error: {exc}", file=err)
        return 1
    finally:
        db.close()
    print(f"Created admin account {created_email}", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
