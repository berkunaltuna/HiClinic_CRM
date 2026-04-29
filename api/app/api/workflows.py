from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import User, Workflow
from app.db.session import get_db
from app.schemas.workflow import WorkflowCreate, WorkflowOut, WorkflowUpdate


router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowOut])
def list_workflows(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkflowOut]:
    return (
        db.query(Workflow)
        .filter(Workflow.owner_user_id == user.id)
        .order_by(Workflow.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = Workflow(
        owner_user_id=user.id,
        name=payload.name,
        trigger_event=payload.trigger_event,
        is_enabled=payload.is_enabled,
        conditions=payload.conditions,
        actions=payload.actions,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.patch("/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = db.get(Workflow, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if payload.name is not None:
        wf.name = payload.name
    if payload.trigger_event is not None:
        wf.trigger_event = payload.trigger_event
    if payload.is_enabled is not None:
        wf.is_enabled = payload.is_enabled
    if payload.conditions is not None:
        wf.conditions = payload.conditions
    if payload.actions is not None:
        wf.actions = payload.actions

    db.commit()
    db.refresh(wf)
    return wf
