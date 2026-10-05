from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Customer, User


def normalise_phone(raw: str | None) -> str | None:
    """Normalise a phone number to +<countrycode><digits> form.

    Extracted from the Facebook lead ingestion path (app.services.facebook_leads) so both
    webhook ingestion and the Excel importer share one implementation.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None

    is_plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if is_plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]

    country = (settings.default_country_code or "+44").strip()
    if digits.startswith("0"):
        digits = digits[1:]
    return f"{country}{digits}"


def normalise_email(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip().lower()
    return text or None


def _phone_suffix(normalised: str, length: int = 9) -> str:
    digits = "".join(ch for ch in normalised if ch.isdigit())
    return digits[-length:] if len(digits) > length else digits


def _scoped_customers(db: Session, user: User):
    q = db.query(Customer)
    if not settings.share_customers_across_users:
        q = q.filter(Customer.owner_user_id == user.id)
    return q


def _find_by_phone(db: Session, user: User, phone: str) -> list[Customer]:
    """Find all customers whose (possibly un-normalised) stored phone matches `phone`
    once both sides are normalised the same way.

    Customers created through POST /customers store phone exactly as typed (never
    normalised), unlike Facebook-ingested customers. A plain `Customer.phone == phone`
    filter would silently miss those, so this does a cheap SQL suffix prefilter (robust to
    leading '+', '00', or a dropped trunk '0') and then confirms each candidate in Python
    with the same normalise_phone() used on the import side, discarding any prefilter
    false-positive.
    """
    suffix = _phone_suffix(phone)
    if not suffix:
        return []
    q = _scoped_customers(db, user).filter(
        Customer.phone.isnot(None),
        sa.func.right(sa.func.regexp_replace(Customer.phone, r"\D", "", "g"), len(suffix)) == suffix,
    )
    return [c for c in q.all() if normalise_phone(c.phone) == phone]


def _find_by_email(db: Session, user: User, email: str) -> list[Customer]:
    return (
        _scoped_customers(db, user)
        .filter(Customer.email.isnot(None), sa.func.lower(Customer.email) == email)
        .all()
    )


@dataclass
class Resolution:
    customer: Customer | None
    status: str  # "matched" | "new" | "review"
    reasons: list[str] = field(default_factory=list)
    matched_via: str | None = None  # "id" | "phone" | "email", set only when status == "matched"


@dataclass
class MatchCandidates:
    id_customer: Customer | None
    id_was_invalid: bool
    phone_matches: list[Customer] = field(default_factory=list)
    email_matches: list[Customer] = field(default_factory=list)
    had_any_identifier: bool = False

    def resolve(self) -> Resolution:
        if self.id_was_invalid:
            return Resolution(None, "review", ["customer id not found"])
        if len(self.phone_matches) > 1:
            return Resolution(None, "review", ["multiple existing customers share this phone number"])
        if len(self.email_matches) > 1:
            return Resolution(None, "review", ["multiple existing customers share this email address"])

        distinct: dict[UUID, Customer] = {}
        sources: dict[UUID, list[str]] = {}
        for label, cust in (
            ("customer id", self.id_customer),
            ("phone", self.phone_matches[0] if self.phone_matches else None),
            ("email", self.email_matches[0] if self.email_matches else None),
        ):
            if cust is None:
                continue
            distinct[cust.id] = cust
            sources.setdefault(cust.id, []).append(label)

        if not self.had_any_identifier:
            return Resolution(
                None,
                "review",
                ["row has no customer ID, phone, or email — cannot be reliably deduplicated on re-import"],
            )

        if len(distinct) > 1:
            names = [f"{cust.name} (via {', '.join(sources[cid])})" for cid, cust in distinct.items()]
            return Resolution(None, "review", ["identifiers point to different existing customers: " + "; ".join(names)])

        if len(distinct) == 1:
            cid, cust = next(iter(distinct.items()))
            via_label = sources[cid][0]
            via = {"customer id": "id", "phone": "phone", "email": "email"}[via_label]
            return Resolution(cust, "matched", matched_via=via)

        return Resolution(None, "new")


def find_customer_candidates(
    db: Session,
    user: User,
    *,
    customer_id: UUID | None = None,
    phone: str | None = None,
    email: str | None = None,
) -> MatchCandidates:
    id_customer: Customer | None = None
    id_was_invalid = False
    if customer_id is not None:
        found = db.get(Customer, customer_id)
        if found is None or (not settings.share_customers_across_users and found.owner_user_id != user.id):
            id_was_invalid = True
        else:
            id_customer = found

    phone_matches = _find_by_phone(db, user, phone) if phone else []
    email_matches = _find_by_email(db, user, email) if email else []

    return MatchCandidates(
        id_customer=id_customer,
        id_was_invalid=id_was_invalid,
        phone_matches=phone_matches,
        email_matches=email_matches,
        had_any_identifier=bool(customer_id or phone or email),
    )
