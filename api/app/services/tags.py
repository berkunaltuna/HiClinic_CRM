from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerTag, Tag


def get_or_create_tag(db: Session, *, owner_user_id, name: str, color: str | None = None) -> Tag:
    """Get a tag by name or create it.

    Tags are owner-scoped.
    """

    clean = (name or "").strip()
    if not clean:
        raise ValueError("Tag name cannot be empty")

    tag = (
        db.query(Tag)
        .filter(Tag.owner_user_id == owner_user_id)
        .filter(Tag.name == clean)
        .first()
    )
    if tag:
        return tag

    tag = Tag(owner_user_id=owner_user_id, name=clean, color=color)
    db.add(tag)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # concurrent creation - retry
        tag = (
            db.query(Tag)
            .filter(Tag.owner_user_id == owner_user_id)
            .filter(Tag.name == clean)
            .first()
        )
        if tag is None:
            raise
    return tag


def add_tag_to_customer(db: Session, *, customer: Customer, tag_name: str, color: str | None = None) -> CustomerTag:
    tag = get_or_create_tag(db, owner_user_id=customer.owner_user_id, name=tag_name, color=color)

    existing = (
        db.query(CustomerTag)
        .filter(CustomerTag.customer_id == customer.id)
        .filter(CustomerTag.tag_id == tag.id)
        .first()
    )
    if existing:
        return existing

    link = CustomerTag(owner_user_id=customer.owner_user_id, customer_id=customer.id, tag_id=tag.id)
    db.add(link)
    db.flush()
    return link


def remove_tag_from_customer(db: Session, *, customer: Customer, tag_name: str) -> bool:
    tag = (
        db.query(Tag)
        .filter(Tag.owner_user_id == customer.owner_user_id)
        .filter(Tag.name == (tag_name or "").strip())
        .first()
    )
    if not tag:
        return False
    link = (
        db.query(CustomerTag)
        .filter(CustomerTag.customer_id == customer.id)
        .filter(CustomerTag.tag_id == tag.id)
        .first()
    )
    if not link:
        return False
    db.delete(link)
    db.flush()
    return True
