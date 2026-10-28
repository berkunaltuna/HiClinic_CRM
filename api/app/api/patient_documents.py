"""Staff routes for private patient documents (proforma invoices).

Uploads stream into the same private storage as photos; nothing is served statically.
Replacing a proforma supersedes the old one (kept for the record), never deletes it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.deps import get_authenticated_user
from app.core.config import settings
from app.db.models import Customer, PatientDocument, User
from app.db.session import get_db
from app.services.audit import record_audit
from app.services.photo_permissions import can_access_customer, require_permission
from app.services.photo_portal_auth import now_utc
from app.services.photo_storage import (
    FORMATS,
    PhotoWriter,
    format_for_upload,
    get_photo_storage,
    sanitize_filename,
    stream_upload_to_writer,
)

router = APIRouter(tags=["patient-documents"])

ENTITY = "patient_document"
PROFORMA = "proforma"

DOCUMENT_RESPONSE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
}


class DocumentOut(BaseModel):
    id: UUID
    category: str
    original_filename: str | None = None
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by_email: str | None = None
    superseded_at: datetime | None = None


class ProformaOut(BaseModel):
    current: DocumentOut | None = None
    history: list[DocumentOut]
    max_file_size_bytes: int
    allowed_extensions: list[str]


def document_out(d: PatientDocument) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        category=d.category,
        original_filename=d.original_filename,
        content_type=d.content_type,
        size_bytes=d.size_bytes,
        uploaded_at=d.uploaded_at,
        uploaded_by_email=d.uploaded_by.email if d.uploaded_by is not None else None,
        superseded_at=d.superseded_at,
    )


def current_proforma(db: Session, customer_id: UUID) -> PatientDocument | None:
    return (
        db.query(PatientDocument)
        .filter(PatientDocument.customer_id == customer_id, PatientDocument.category == PROFORMA, PatientDocument.superseded_at.is_(None))
        .order_by(PatientDocument.uploaded_at.desc())
        .first()
    )


def _customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    # Same 404 for "missing" and "not yours", so IDs cannot be probed.
    if customer is None or not can_access_customer(db, user, customer):
        raise HTTPException(status_code=404, detail="Patient not found")
    return customer


def _proforma_types() -> tuple[list[str], int]:
    exts: list[str] = []
    for name in settings.proforma_allowed_formats:
        if name in FORMATS:
            exts += sorted(FORMATS[name]["extensions"])
    return exts, settings.proforma_max_file_size_mb * 1024 * 1024


@router.get("/customers/{customer_id}/proforma", response_model=ProformaOut)
def get_proforma(customer_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> ProformaOut:
    require_permission(user, "proforma.view")
    customer = _customer(db, customer_id, user)
    docs = (
        db.query(PatientDocument)
        .filter(PatientDocument.customer_id == customer.id, PatientDocument.category == PROFORMA)
        .order_by(PatientDocument.uploaded_at.desc())
        .all()
    )
    exts, max_bytes = _proforma_types()
    current = next((d for d in docs if d.superseded_at is None), None)
    return ProformaOut(
        current=document_out(current) if current else None,
        history=[document_out(d) for d in docs],
        max_file_size_bytes=max_bytes,
        allowed_extensions=exts,
    )


def _finalize_proforma(db: Session, customer_id: UUID, user: User, writer: PhotoWriter, fmt: str, filename: str) -> PatientDocument:
    # Lock the patient so two uploads cannot both become "current".
    db.query(Customer).filter(Customer.id == customer_id).with_for_update().one()
    previous = current_proforma(db, customer_id)
    storage = get_photo_storage()
    key = storage.new_key(fmt)
    writer.commit(key)
    try:
        doc = PatientDocument(
            customer_id=customer_id,
            category=PROFORMA,
            storage_key=key,
            original_filename=sanitize_filename(filename),
            content_type=FORMATS[fmt]["content_type"],
            size_bytes=writer.bytes_written,
            sha256=writer.sha256.hexdigest(),
            uploaded_by_user_id=user.id,
        )
        db.add(doc)
        db.flush()
        if previous is not None:
            previous.superseded_at = now_utc()
            previous.superseded_by_id = doc.id
        record_audit(
            db,
            actor=user,
            action="patient_document.replaced" if previous is not None else "patient_document.uploaded",
            entity_type=ENTITY,
            entity_id=doc.id,
            after={"category": PROFORMA, "size_bytes": doc.size_bytes},
            metadata={"customer_id": str(customer_id), "replaced_document_id": str(previous.id) if previous else None},
        )
        db.commit()
        db.refresh(doc)
        return doc
    except Exception:
        db.rollback()
        storage.delete(key)
        raise


@router.put("/customers/{customer_id}/proforma", response_model=DocumentOut, status_code=201)
async def upload_proforma(
    customer_id: UUID,
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> DocumentOut:
    """Upload (or replace) the patient's proforma as the raw request body, streamed to private storage."""
    require_permission(user, "proforma.upload")
    await run_in_threadpool(_customer, db, customer_id, user)
    fmt = format_for_upload(filename, request.headers.get("content-type", ""), settings.proforma_allowed_formats)
    if fmt is None:
        raise HTTPException(status_code=415, detail="Proforma invoices must be PDF files")
    _exts, max_bytes = _proforma_types()
    writer = await stream_upload_to_writer(
        request, fmt=fmt, max_bytes=max_bytes, too_big_detail=f"Proformas must be {settings.proforma_max_file_size_mb} MB or smaller"
    )
    try:
        doc = await run_in_threadpool(_finalize_proforma, db, customer_id, user, writer, fmt, filename)
    except BaseException:
        await run_in_threadpool(writer.abort)
        raise
    return document_out(doc)


def stream_document(doc: PatientDocument, disposition: str) -> StreamingResponse:
    storage = get_photo_storage()
    try:
        size = storage.size(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document file is missing from storage")
    ext = doc.storage_key.rsplit(".", 1)[-1]
    return StreamingResponse(
        storage.iter_bytes(doc.storage_key),
        media_type=doc.content_type,
        headers={
            **DOCUMENT_RESPONSE_HEADERS,
            "Content-Length": str(size),
            "Content-Disposition": f'{disposition}; filename="{doc.category}-{doc.id}.{ext}"',
        },
    )


@router.get("/customers/{customer_id}/proforma/{document_id}/content")
def get_proforma_content(
    customer_id: UUID,
    document_id: UUID,
    download: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> StreamingResponse:
    require_permission(user, "proforma.view")
    customer = _customer(db, customer_id, user)
    doc = db.get(PatientDocument, document_id)
    if doc is None or doc.customer_id != customer.id or doc.category != PROFORMA:
        raise HTTPException(status_code=404, detail="Document not found")
    record_audit(
        db,
        actor=user,
        action="patient_document.downloaded" if download else "patient_document.viewed",
        entity_type=ENTITY,
        entity_id=doc.id,
        metadata={"customer_id": str(customer.id)},
    )
    db.commit()
    return stream_document(doc, "attachment" if download else "inline")
