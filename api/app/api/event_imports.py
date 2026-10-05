from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.events import _get_event
from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.models import ImportBatch, ImportRow, User
from app.db.session import get_db
from app.schemas.event_import import ImportBatchOut, ImportMappingIn, ImportResultOut, ImportRowOut, ImportUploadOut
from app.services.event_export import build_error_report, build_export_workbook
from app.services.event_import import create_batch_from_upload, run_commit, run_preview, suggest_mapping

router = APIRouter(prefix="/events", tags=["event-imports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _get_batch_for_event(db: Session, event_id: UUID, batch_id: UUID, user: User) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.event_id != event_id:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if not settings.share_customers_across_users and batch.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return batch


def _result_out(batch: ImportBatch, db: Session) -> ImportResultOut:
    rows = (
        db.query(ImportRow)
        .filter(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number.asc())
        .all()
    )
    return ImportResultOut(batch=ImportBatchOut.model_validate(batch), rows=[ImportRowOut.model_validate(r) for r in rows])


@router.get("/{event_id}/export.xlsx")
def export_event_bookings(
    event_id: UUID,
    day: date | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    event = _get_event(db, event_id)
    content = build_export_workbook(db, event, day=day, status=status)
    filename = f"{event.name or 'event'}-bookings.xlsx".replace(" ", "_")
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{event_id}/imports/upload", response_model=ImportUploadOut, status_code=201)
async def upload_import(
    event_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportUploadOut:
    event = _get_event(db, event_id)
    content = await file.read()
    batch = create_batch_from_upload(db, event=event, user=user, filename=file.filename or "upload", content=content)
    rows = (
        db.query(ImportRow)
        .filter(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number.asc())
        .limit(20)
        .all()
    )
    headers = list(rows[0].raw_data.keys()) if rows else []
    return ImportUploadOut(
        batch_id=batch.id,
        headers=headers,
        suggested_mapping=suggest_mapping(headers),
        row_count=batch.row_count,
        sample_rows=[r.raw_data for r in rows],
    )


@router.post("/{event_id}/imports/{batch_id}/preview", response_model=ImportResultOut)
def preview_import(
    event_id: UUID,
    batch_id: UUID,
    payload: ImportMappingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResultOut:
    event = _get_event(db, event_id)
    batch = _get_batch_for_event(db, event_id, batch_id, user)
    run_preview(db, batch, event=event, user=user, mapping=payload.mapping)
    batch = _get_batch_for_event(db, event_id, batch_id, user)
    return _result_out(batch, db)


@router.post("/{event_id}/imports/{batch_id}/commit", response_model=ImportResultOut)
def commit_import(
    event_id: UUID,
    batch_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResultOut:
    event = _get_event(db, event_id)
    batch = _get_batch_for_event(db, event_id, batch_id, user)
    batch = run_commit(db, batch, event=event, user=user)
    return _result_out(batch, db)


@router.get("/{event_id}/imports/{batch_id}", response_model=ImportResultOut)
def get_import_batch(
    event_id: UUID,
    batch_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResultOut:
    batch = _get_batch_for_event(db, event_id, batch_id, user)
    return _result_out(batch, db)


@router.get("/{event_id}/imports/{batch_id}/errors.xlsx")
def download_import_errors(
    event_id: UUID,
    batch_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    batch = _get_batch_for_event(db, event_id, batch_id, user)
    content = build_error_report(batch)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="import-errors.xlsx"'},
    )
