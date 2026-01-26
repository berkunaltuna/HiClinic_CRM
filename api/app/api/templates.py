from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from uuid import UUID

from app.auth.deps import get_current_user, require_admin
from app.db.models import Template, User
from app.db.session import get_db
from app.schemas.template import TemplateCreate, TemplateOut, TemplateUpdate
from starlette.status import HTTP_204_NO_CONTENT


router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateOut]:
    # Read access: any authenticated user
    return db.query(Template).order_by(Template.channel.asc(), Template.name.asc()).all()


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    tpl = db.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TemplateOut:
    existing = (
        db.query(Template)
        .filter(Template.channel == payload.channel, Template.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Template name already exists for this channel")

    tpl = Template(
        channel=payload.channel,
        name=payload.name,
        subject=payload.subject,
        body=payload.body,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: UUID,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TemplateOut:
    tpl = db.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Apply updates
    if payload.channel is not None:
        tpl.channel = payload.channel
    if payload.name is not None:
        tpl.name = payload.name
    if payload.subject is not None or (payload.channel == "whatsapp"):
        # if switching to whatsapp, allow clearing subject by explicitly setting subject=None
        tpl.subject = payload.subject
    if payload.body is not None:
        tpl.body = payload.body

    # Enforce unique (channel, name)
    existing = (
        db.query(Template)
        .filter(Template.id != template_id, Template.channel == tpl.channel, Template.name == tpl.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Template name already exists for this channel")

    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl

@router.delete("/{template_id}", status_code=HTTP_204_NO_CONTENT, response_class=Response)
def delete_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    tpl = db.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(tpl)
    db.commit()
    return Response(status_code=HTTP_204_NO_CONTENT)
