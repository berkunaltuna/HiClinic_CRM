from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Customer, Tag, User
from app.db.session import get_db
from app.schemas.tag import TagCreate, TagOut
from app.services.tags import add_tag_to_customer, get_or_create_tag, remove_tag_from_customer


router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TagOut]:
    return (
        db.query(Tag)
        .filter(Tag.owner_user_id == user.id)
        .order_by(Tag.name.asc())
        .limit(500)
        .all()
    )


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TagOut:
    tag = get_or_create_tag(db, owner_user_id=user.id, name=payload.name, color=payload.color)
    db.commit()
    db.refresh(tag)
    return tag


@router.post(
    "/customers/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def add_tag(
    customer_id: UUID,
    payload: TagCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    add_tag_to_customer(db, customer=customer, tag_name=payload.name, color=payload.color)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/customers/{customer_id}/{tag_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_tag(
    customer_id: UUID,
    tag_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    removed = remove_tag_from_customer(db, customer=customer, tag_name=tag_name)
    db.commit()
    if not removed:
        # idempotent delete - don't fail
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
