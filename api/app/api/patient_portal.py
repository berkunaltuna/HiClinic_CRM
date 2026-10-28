"""Patient-facing photo portal (see docs/patient-photos.md).

Patients never use staff credentials. A portal link is exchanged for a short-lived
session that is bound to one photo request; every route below derives the request
from that session, never from an ID in the URL or body, so a patient cannot reach
another request. Responses never include internal notes, assessments or staff data.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.photo_requests import ENTITY, PHOTO_RESPONSE_HEADERS, _add_status_event, allowed_upload_types
from app.core.config import settings
from app.api.patient_documents import current_proforma, stream_document
from app.db.models import DoctorProfile, PatientDocument, PatientPhoto, PhotoAccessLink, PhotoRequest
from app.db.session import get_db
from app.schemas.photo_request import (
    PortalConsentIn,
    PortalConsentOut,
    PortalLimitsOut,
    PortalPhotoOut,
    PortalRequestOut,
    PortalSessionIn,
    PortalSessionOut,
    PortalDoctorOut,
    PortalDocumentLinkOut,
    PortalProformaOut,
)
from app.services.audit import record_audit
from app.services.photo_permissions import active_doctor_assignment
from app.services.photo_portal_auth import (
    create_document_token,
    decode_document_token,
    UPLOADABLE_STATUSES,
    PortalContext,
    client_key,
    create_session_token,
    failed_attempts,
    get_portal_context,
    hash_token,
    is_well_formed,
    link_is_usable,
    now_utc,
)
from app.services.photo_storage import (
    FORMATS,
    PhotoWriter,
    format_for_upload,
    get_photo_storage,
    sanitize_filename,
    stream_upload_to_writer,
)

router = APIRouter(prefix="/portal/photo-request", tags=["patient-portal"])

TERMINAL_STATUSES = ("closed", "withdrawn")

CONSENT_TEXT = (
    "Your photos will be reviewed by {reviewer} to assess the enquiry described above.\n"
    "Photos are treated as confidential health information. They are stored privately, are only "
    "accessible to authorised clinic staff, and are never sent by WhatsApp, email or other messages.\n"
    "Only upload photos of the area described in the request, and avoid including other people.\n"
    "You can ask the clinic to withdraw this request and stop using your photos at any time.\n"
    "By ticking the box you agree to the clinic storing and reviewing these photos for this purpose."
)

_PORTAL_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _patient_audit(db: Session, ctx: PortalContext, action: str, **metadata) -> None:
    record_audit(
        db,
        actor=None,
        action=action,
        entity_type=ENTITY,
        entity_id=ctx.request.id,
        metadata={"actor_type": "patient", "link_id": str(ctx.link.id), **metadata},
    )


def _current_photos(db: Session, req: PhotoRequest) -> list[PatientPhoto]:
    return (
        db.query(PatientPhoto)
        .filter(
            PatientPhoto.request_id == req.id,
            PatientPhoto.upload_round == req.upload_round,
            PatientPhoto.deleted_at.is_(None),
        )
        .order_by(PatientPhoto.uploaded_at.asc())
        .all()
    )


def _max_bytes() -> int:
    return settings.photo_max_file_size_mb * 1024 * 1024


def _portal_photo(p: PatientPhoto) -> PortalPhotoOut:
    return PortalPhotoOut(
        id=p.id,
        original_filename=p.original_filename,
        content_type=p.content_type,
        size_bytes=p.size_bytes,
        uploaded_at=p.uploaded_at,
    )


# --- session -------------------------------------------------------------------


@router.post("/session", response_model=PortalSessionOut)
def open_session(payload: PortalSessionIn, request: Request, response: Response, db: Session = Depends(get_db)) -> PortalSessionOut:
    """Exchange a portal link token for a short-lived session bound to its request."""
    response.headers.update(_PORTAL_HEADERS)
    who = client_key(request)
    if failed_attempts.is_locked(who):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")

    denied = HTTPException(status_code=401, detail="This link has expired or is no longer valid")
    if not is_well_formed(payload.token):
        failed_attempts.record_failure(who)
        raise denied
    link = (
        db.query(PhotoAccessLink)
        .filter(PhotoAccessLink.token_hash == hash_token(payload.token))
        .with_for_update()
        .first()
    )
    if link is None:
        failed_attempts.record_failure(who)
        raise denied

    req = db.get(PhotoRequest, link.request_id)
    reason = None
    if link.revoked_at is not None:
        reason = "revoked"
    elif not link_is_usable(link):
        reason = "expired"
    elif link.use_count >= link.max_uses:
        reason = "max_uses_reached"
    elif req is None or req.status in TERMINAL_STATUSES:
        reason = "request_closed"
    if reason:
        failed_attempts.record_failure(who)
        record_audit(
            db,
            actor=None,
            action="photo_portal.access_denied",
            entity_type=ENTITY,
            entity_id=link.request_id,
            metadata={"actor_type": "patient", "link_id": str(link.id), "reason": reason},
        )
        db.commit()
        raise denied

    link.use_count += 1
    link.last_used_at = now_utc()
    token, expires_at = create_session_token(link)
    record_audit(
        db,
        actor=None,
        action="photo_portal.session_opened",
        entity_type=ENTITY,
        entity_id=req.id,
        metadata={"actor_type": "patient", "link_id": str(link.id), "use_count": link.use_count},
    )
    db.commit()
    return PortalSessionOut(session_token=token, expires_at=expires_at)


# --- request -------------------------------------------------------------------


@router.get("", response_model=PortalRequestOut)
def get_portal_request(response: Response, ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> PortalRequestOut:
    response.headers.update(_PORTAL_HEADERS)
    req = ctx.request
    exts, mimes = allowed_upload_types()
    consent_current = req.consent_accepted_at is not None and req.consent_version == settings.photo_consent_version
    first_name = (req.customer.name or "").strip().split(" ")[0] if req.customer else ""
    return PortalRequestOut(
        title=req.title,
        instructions=req.instructions,
        patient_message=req.patient_message if req.status == "more_photos_needed" else None,
        status=req.status,
        patient_first_name=first_name,
        reviewer=settings.photo_reviewer_description,
        can_upload=req.status in UPLOADABLE_STATUSES,
        consent=PortalConsentOut(
            version=settings.photo_consent_version,
            text=CONSENT_TEXT.format(reviewer=settings.photo_reviewer_description),
            accepted=consent_current,
            accepted_at=req.consent_accepted_at if consent_current else None,
        ),
        limits=PortalLimitsOut(
            max_file_size_bytes=_max_bytes(),
            max_files=settings.photo_max_files_per_request,
            allowed_extensions=exts,
            allowed_mime_types=mimes,
        ),
        photos=[_portal_photo(p) for p in _current_photos(db, req)],
        submitted_at=req.submitted_at,
        created_at=req.created_at,
        proforma=_portal_proforma(db, req),
        doctor=_portal_doctor(db, req),
    )


def _portal_proforma(db: Session, req: PhotoRequest) -> PortalProformaOut:
    doc = current_proforma(db, req.customer_id)
    if doc is None:
        return PortalProformaOut(available=False)
    return PortalProformaOut(available=True, filename=doc.original_filename, uploaded_at=doc.uploaded_at)


def _portal_doctor(db: Session, req: PhotoRequest) -> PortalDoctorOut | None:
    """The assigned doctor's patient-facing profile, only if an admin made it visible."""
    assignment = active_doctor_assignment(db, req.customer_id)
    if assignment is None:
        return None
    profile = db.get(DoctorProfile, assignment.doctor_user_id)
    if profile is None or not profile.visible_to_patients or not (profile.display_name or "").strip():
        return None
    return PortalDoctorOut(display_name=profile.display_name, title=profile.title, specialty=profile.specialty, bio=profile.bio)


@router.post("/proforma/link", response_model=PortalDocumentLinkOut)
def proforma_link(ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> PortalDocumentLinkOut:
    """A short-lived link to open this patient's own current proforma (no public file URL)."""
    doc = current_proforma(db, ctx.request.customer_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No proforma invoice is available yet")
    token, expires_at = create_document_token(ctx.link, doc.id, ctx.request.customer_id)
    _patient_audit(db, ctx, "patient_document.link_issued_to_patient", document_id=str(doc.id))
    db.commit()
    return PortalDocumentLinkOut(url=f"/portal/photo-request/proforma/content?token={token}", expires_at=expires_at)


@router.get("/proforma/content")
def proforma_content(token: str = Query(max_length=2000), db: Session = Depends(get_db)) -> StreamingResponse:
    denied = HTTPException(status_code=401, detail="This document link has expired. Please open it again from your page.")
    try:
        claims = decode_document_token(token)
        doc_id, customer_id, link_id = UUID(claims["sub"]), UUID(claims["cid"]), UUID(claims["lid"])
    except Exception:
        raise denied
    link = db.get(PhotoAccessLink, link_id)
    req = db.get(PhotoRequest, link.request_id) if link is not None else None
    doc = db.get(PatientDocument, doc_id)
    if (
        link is None
        or not link_is_usable(link)
        or req is None
        or req.status in TERMINAL_STATUSES
        or req.customer_id != customer_id
        or doc is None
        or doc.customer_id != customer_id
        or doc.superseded_at is not None
    ):
        raise denied
    record_audit(
        db,
        actor=None,
        action="patient_document.viewed_by_patient",
        entity_type="patient_document",
        entity_id=doc.id,
        metadata={"actor_type": "patient", "link_id": str(link.id), "customer_id": str(customer_id)},
    )
    db.commit()
    return stream_document(doc, "inline")


@router.post("/consent", status_code=204, response_class=Response)
def record_consent(payload: PortalConsentIn, ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> Response:
    if payload.version != settings.photo_consent_version:
        raise HTTPException(status_code=409, detail="The consent wording has changed. Please reload the page.")
    req = db.query(PhotoRequest).filter(PhotoRequest.id == ctx.request.id).with_for_update().one()
    if req.status not in UPLOADABLE_STATUSES:
        raise HTTPException(status_code=409, detail="This request is not accepting photos")
    if req.consent_accepted_at is None or req.consent_version != payload.version:
        req.consent_version = payload.version
        req.consent_accepted_at = now_utc()
        req.consent_link_id = ctx.link.id
        _patient_audit(db, ctx, "photo_request.consent_recorded", consent_version=payload.version)
        db.commit()
    return Response(status_code=204)


# --- upload --------------------------------------------------------------------


def _precheck_upload(db: Session, ctx: PortalContext) -> None:
    req = ctx.request
    if req.status not in UPLOADABLE_STATUSES:
        raise HTTPException(status_code=409, detail="This request is not accepting photos")
    if req.consent_accepted_at is None or req.consent_version != settings.photo_consent_version:
        raise HTTPException(status_code=403, detail="Please read and accept the consent statement first")
    if len(_current_photos(db, req)) >= settings.photo_max_files_per_request:
        raise HTTPException(status_code=409, detail=f"You can upload up to {settings.photo_max_files_per_request} photos")


def _finalize_upload(
    db: Session,
    ctx: PortalContext,
    writer: PhotoWriter,
    fmt: str,
    filename: str,
) -> PatientPhoto:
    # Lock the request so concurrent uploads cannot exceed the photo limit.
    req = db.query(PhotoRequest).filter(PhotoRequest.id == ctx.request.id).with_for_update().one()
    ctx.request = req
    _precheck_upload(db, ctx)
    storage = get_photo_storage()
    key = storage.new_key(fmt)
    writer.commit(key)
    try:
        photo = PatientPhoto(
            request_id=req.id,
            storage_key=key,
            original_filename=sanitize_filename(filename),
            content_type=FORMATS[fmt]["content_type"],
            size_bytes=writer.bytes_written,
            sha256=writer.sha256.hexdigest(),
            upload_round=req.upload_round,
            uploaded_via_link_id=ctx.link.id,
        )
        db.add(photo)
        db.flush()
        req.updated_at = now_utc()
        _patient_audit(db, ctx, "patient_photo.uploaded", photo_id=str(photo.id), size_bytes=photo.size_bytes, format=fmt)
        db.commit()
        db.refresh(photo)
        return photo
    except Exception:
        db.rollback()
        storage.delete(key)
        raise


@router.put("/photos", response_model=PortalPhotoOut, status_code=201)
async def upload_photo(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    ctx: PortalContext = Depends(get_portal_context),
    db: Session = Depends(get_db),
) -> PortalPhotoOut:
    """Upload one photo as the raw request body.

    The body is streamed straight to a private temp file in small chunks (no multipart
    parsing, no full-file buffering), size-limited while streaming, and its leading bytes
    must match the declared extension and MIME type before it is kept.
    """
    await run_in_threadpool(_precheck_upload, db, ctx)

    fmt = format_for_upload(filename, request.headers.get("content-type", ""))
    if fmt is None:
        raise HTTPException(status_code=415, detail="Unsupported file type. Please upload a JPEG, PNG, WebP or HEIC photo.")

    writer = await stream_upload_to_writer(
        request,
        fmt=fmt,
        max_bytes=_max_bytes(),
        too_big_detail=f"Photos must be {settings.photo_max_file_size_mb} MB or smaller",
    )
    try:
        photo = await run_in_threadpool(_finalize_upload, db, ctx, writer, fmt, filename)
    except BaseException:
        await run_in_threadpool(writer.abort)
        raise
    return _portal_photo(photo)


def _patient_photo(db: Session, ctx: PortalContext, photo_id: UUID) -> PatientPhoto:
    photo = db.get(PatientPhoto, photo_id)
    # Same 404 for "not yours" and "does not exist".
    if photo is None or photo.request_id != ctx.request.id or photo.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/photos/{photo_id}/content")
def get_own_photo(photo_id: UUID, ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> StreamingResponse:
    photo = _patient_photo(db, ctx, photo_id)
    storage = get_photo_storage()
    try:
        size = storage.size(photo.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Photo not found")
    _patient_audit(db, ctx, "patient_photo.viewed_by_patient", photo_id=str(photo.id))
    db.commit()
    return StreamingResponse(
        storage.iter_bytes(photo.storage_key),
        media_type=photo.content_type,
        headers={**PHOTO_RESPONSE_HEADERS, "Content-Length": str(size), "Content-Disposition": "inline"},
    )


@router.delete("/photos/{photo_id}", status_code=204, response_class=Response)
def remove_own_photo(photo_id: UUID, ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> Response:
    """Before submitting, a patient may remove a photo they uploaded in this round.

    The metadata row is kept (soft delete) for the audit trail; the image itself is
    erased because the patient withdrew it before anyone reviewed it.
    """
    req = db.query(PhotoRequest).filter(PhotoRequest.id == ctx.request.id).with_for_update().one()
    photo = _patient_photo(db, ctx, photo_id)
    if req.status not in UPLOADABLE_STATUSES or photo.upload_round != req.upload_round:
        raise HTTPException(status_code=409, detail="Submitted photos can no longer be removed. Please contact the clinic.")
    photo.deleted_at = now_utc()
    photo.delete_reason = "removed by patient before submission"
    _patient_audit(db, ctx, "patient_photo.removed_by_patient", photo_id=str(photo.id))
    db.commit()
    get_photo_storage().delete(photo.storage_key)
    return Response(status_code=204)


@router.post("/submit", response_model=PortalRequestOut)
def submit(response: Response, ctx: PortalContext = Depends(get_portal_context), db: Session = Depends(get_db)) -> PortalRequestOut:
    req = db.query(PhotoRequest).filter(PhotoRequest.id == ctx.request.id).with_for_update().one()
    if req.status not in UPLOADABLE_STATUSES:
        raise HTTPException(status_code=409, detail="These photos have already been submitted")
    photos = _current_photos(db, req)
    if not photos:
        raise HTTPException(status_code=422, detail="Please upload at least one photo first")
    _add_status_event(db, req, "uploaded", None, None)
    before = req.status
    req.status = "uploaded"
    req.submitted_at = now_utc()
    req.updated_at = req.submitted_at
    record_audit(
        db,
        actor=None,
        action="photo_request.status_changed",
        entity_type=ENTITY,
        entity_id=req.id,
        before={"status": before},
        after={"status": "uploaded"},
        metadata={"actor_type": "patient", "link_id": str(ctx.link.id), "photo_count": len(photos)},
    )
    db.commit()
    ctx.request = req
    return get_portal_request(response, ctx, db)
