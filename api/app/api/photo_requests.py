"""Staff endpoints for patient photo requests (see docs/patient-photos.md).

Every route re-checks the caller's role (app.services.photo_permissions) and their
access to the patient; the frontend only mirrors these rules.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.deps import get_authenticated_user
from app.core.config import settings
from app.db.models import (
    Appointment,
    Customer,
    Deal,
    DoctorProfile,
    PhotoRequestEmail,
    PatientPhoto,
    PhotoAccessLink,
    PhotoClinicalAssessment,
    PhotoEntryRevision,
    PhotoRequest,
    PhotoRequestNote,
    PhotoRequestStatusEvent,
    User,
)
from app.db.session import get_db
from app.schemas.photo_request import (
    EntryIn,
    EntryOut,
    EntryRevisionOut,
    AssignedDoctorOut,
    IssuedLinkOut,
    PhotoEmailOut,
    SendEmailIn,
    LinkOption,
    LinkRevokeIn,
    PatientPhotoOut,
    PhotoAccessLinkOut,
    PhotoHideIn,
    PhotoLinkOptionsOut,
    PhotoRequestCreate,
    PhotoRequestDetailOut,
    PhotoRequestOut,
    PhotoRequestQueueItem,
    StatusChangeIn,
    StatusEventOut,
)
from app.services.audit import record_audit
from app.services.photo_permissions import (
    can_access_customer,
    has_permission,
    permissions_for,
    require_permission,
    role_of,
    active_doctor_assignment,
    customer_scope,
)
from app.services.photo_portal_auth import (
    UPLOADABLE_STATUSES,
    generate_link_token,
    hash_token,
    link_is_usable,
    now_utc,
)
from app.services import photo_request_email as emailing
from app.services.photo_storage import FORMATS, get_photo_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["photo-requests"])

ENTITY = "photo_request"

# target status -> (allowed source statuses, required permission)
STAFF_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "in_review": (frozenset({"uploaded", "reviewed"}), "photo_request.manage_status"),
    "more_photos_needed": (frozenset({"uploaded", "in_review", "reviewed"}), "photo_request.request_more"),
    "reviewed": (frozenset({"uploaded", "in_review"}), "photo_request.mark_reviewed"),
    "closed": (
        frozenset({"requested", "uploaded", "in_review", "more_photos_needed", "reviewed"}),
        "photo_request.manage_status",
    ),
    "withdrawn": (
        frozenset({"requested", "uploaded", "in_review", "more_photos_needed"}),
        "photo_request.manage_status",
    ),
}

# Defence in depth for the authenticated photo stream.
PHOTO_RESPONSE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
}


# --- helpers -------------------------------------------------------------------


def _get_customer(db: Session, customer_id: UUID, user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or not can_access_customer(db, user, customer):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _get_request(db: Session, request_id: UUID, user: User, *, lock: bool = False) -> PhotoRequest:
    q = db.query(PhotoRequest).filter(PhotoRequest.id == request_id)
    if lock:
        q = q.with_for_update()
    req = q.first()
    # 404 (not 403) for requests on patients the caller cannot see, so IDs cannot be probed.
    if req is None or not can_access_customer(db, user, req.customer):
        raise HTTPException(status_code=404, detail="Photo request not found")
    return req


def _photo_count(db: Session, request_id: UUID) -> int:
    return (
        db.query(func.count(PatientPhoto.id))
        .filter(PatientPhoto.request_id == request_id, PatientPhoto.deleted_at.is_(None))
        .scalar()
        or 0
    )


def _latest_email(db: Session, request_id: UUID) -> PhotoRequestEmail | None:
    return (
        db.query(PhotoRequestEmail)
        .filter(PhotoRequestEmail.request_id == request_id)
        .order_by(PhotoRequestEmail.created_at.desc())
        .first()
    )


def _email_out(row: PhotoRequestEmail) -> PhotoEmailOut:
    msg = row.outbound_message
    return PhotoEmailOut(
        id=row.id,
        to_email=row.to_email,
        status=msg.status if msg is not None else None,
        last_error=msg.last_error if msg is not None else None,
        sent_by_email=row.sent_by.email if row.sent_by is not None else None,
        created_at=row.created_at,
    )


def _request_out(db: Session, req: PhotoRequest) -> PhotoRequestOut:
    email = _latest_email(db, req.id)
    return PhotoRequestOut(
        id=req.id,
        customer_id=req.customer_id,
        appointment_id=req.appointment_id,
        deal_id=req.deal_id,
        title=req.title,
        instructions=req.instructions,
        patient_message=req.patient_message,
        status=req.status,
        upload_round=req.upload_round,
        consent_version=req.consent_version,
        consent_accepted_at=req.consent_accepted_at,
        consent_status=req.consent_status,
        submitted_at=req.submitted_at,
        closed_at=req.closed_at,
        created_by_email=req.created_by.email if req.created_by is not None else None,
        photo_count=_photo_count(db, req.id),
        email_status=email.outbound_message.status if email is not None and email.outbound_message is not None else None,
        emailed_at=email.created_at if email is not None else None,
        emailed_by_email=email.sent_by.email if email is not None and email.sent_by is not None else None,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


def _link_out(link: PhotoAccessLink) -> PhotoAccessLinkOut:
    return PhotoAccessLinkOut(
        id=link.id,
        created_at=link.created_at,
        expires_at=link.expires_at,
        max_uses=link.max_uses,
        use_count=link.use_count,
        last_used_at=link.last_used_at,
        revoked_at=link.revoked_at,
        revoke_reason=link.revoke_reason,
        active=link_is_usable(link) and link.use_count < link.max_uses,
    )


def _revoke_active_links(db: Session, req: PhotoRequest, user: User | None, reason: str) -> list[UUID]:
    revoked = []
    now = now_utc()
    for link in db.query(PhotoAccessLink).filter(
        PhotoAccessLink.request_id == req.id, PhotoAccessLink.revoked_at.is_(None)
    ):
        link.revoked_at = now
        link.revoked_by_user_id = getattr(user, "id", None)
        link.revoke_reason = reason
        revoked.append(link.id)
    return revoked


def _issue_link(db: Session, req: PhotoRequest, user: User) -> tuple[PhotoAccessLink, str]:
    """Create a fresh portal link (revoking older ones); returns the raw token once."""
    if req.status not in UPLOADABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Links can only be issued while photos are being requested")
    revoked = _revoke_active_links(db, req, user, "replaced")
    token = generate_link_token()
    link = PhotoAccessLink(
        request_id=req.id,
        token_hash=hash_token(token),
        created_by_user_id=user.id,
        expires_at=now_utc() + timedelta(hours=settings.photo_link_ttl_hours),
        max_uses=settings.photo_link_max_uses,
        use_count=0,
    )
    db.add(link)
    db.flush()
    db.refresh(link)
    record_audit(
        db,
        actor=user,
        action="photo_request.link_issued",
        entity_type=ENTITY,
        entity_id=req.id,
        metadata={"link_id": str(link.id), "expires_at": link.expires_at.isoformat(), "revoked_link_ids": [str(i) for i in revoked]},
    )
    return link, token


def _portal_url(token: str) -> str:
    # The token goes in the URL fragment, which browsers never send to servers or in Referer headers.
    return f"{settings.frontend_base_url.rstrip('/')}/portal/photos#token={token}"


def _add_status_event(db: Session, req: PhotoRequest, to_status: str, user: User | None, reason: str | None) -> None:
    db.add(
        PhotoRequestStatusEvent(
            request_id=req.id,
            from_status=req.status if req.status != to_status else None,
            to_status=to_status,
            actor_type="staff" if user is not None else "patient",
            actor_user_id=getattr(user, "id", None),
            actor_email=getattr(user, "email", None),
            actor_role=role_of(user) if user is not None else None,
            reason=reason,
        )
    )


def _entries_out(db: Session, rows, entry_type: str) -> list[EntryOut]:
    out = []
    for row in rows:
        revisions = (
            db.query(PhotoEntryRevision)
            .filter(PhotoEntryRevision.entry_type == entry_type, PhotoEntryRevision.entry_id == row.id)
            .order_by(PhotoEntryRevision.version.asc())
            .all()
        )
        out.append(
            EntryOut(
                id=row.id,
                author_user_id=row.author_user_id,
                author_email=row.author_email,
                author_role=row.author_role,
                body=row.body,
                version=row.version,
                created_at=row.created_at,
                updated_at=row.updated_at,
                revisions=[EntryRevisionOut.model_validate(r) for r in revisions],
            )
        )
    return out


def _detail(db: Session, req: PhotoRequest, user: User) -> PhotoRequestDetailOut:
    photos = notes = assessments = None
    if has_permission(user, "photo.view"):
        photos = [
            PatientPhotoOut.model_validate(p)
            for p in db.query(PatientPhoto)
            .filter(PatientPhoto.request_id == req.id)
            .order_by(PatientPhoto.uploaded_at.asc())
        ]
    if has_permission(user, "note.view"):
        notes = _entries_out(
            db,
            db.query(PhotoRequestNote).filter(PhotoRequestNote.request_id == req.id).order_by(PhotoRequestNote.created_at.asc()),
            "note",
        )
    if has_permission(user, "assessment.view"):
        assessments = _entries_out(
            db,
            db.query(PhotoClinicalAssessment)
            .filter(PhotoClinicalAssessment.request_id == req.id)
            .order_by(PhotoClinicalAssessment.created_at.asc()),
            "assessment",
        )
    links = db.query(PhotoAccessLink).filter(PhotoAccessLink.request_id == req.id).order_by(PhotoAccessLink.created_at.desc())
    history = (
        db.query(PhotoRequestStatusEvent)
        .filter(PhotoRequestStatusEvent.request_id == req.id)
        .order_by(PhotoRequestStatusEvent.created_at.asc())
    )
    emails = (
        db.query(PhotoRequestEmail).filter(PhotoRequestEmail.request_id == req.id).order_by(PhotoRequestEmail.created_at.desc()).all()
    )
    assignment = active_doctor_assignment(db, req.customer_id)
    assigned_doctor = None
    if assignment is not None:
        profile = db.get(DoctorProfile, assignment.doctor_user_id)
        assigned_doctor = AssignedDoctorOut(
            id=assignment.doctor_user_id,
            email=assignment.doctor.email,
            display_name=profile.display_name if profile is not None else None,
        )
    return PhotoRequestDetailOut(
        request=_request_out(db, req),
        customer_name=req.customer.name,
        permissions=permissions_for(user),
        photos=photos,
        notes=notes,
        assessments=assessments,
        links=[_link_out(link) for link in links],
        history=[StatusEventOut.model_validate(e) for e in history],
        emails=[_email_out(e) for e in emails],
        assigned_doctor=assigned_doctor,
    )


def _touch(req: PhotoRequest) -> None:
    req.updated_at = now_utc()


# --- requests ------------------------------------------------------------------


@router.get("/customers/{customer_id}/photo-requests", response_model=list[PhotoRequestOut])
def list_customer_photo_requests(
    customer_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> list[PhotoRequestOut]:
    require_permission(user, "photo_request.view_summary")
    _get_customer(db, customer_id, user)
    rows = (
        db.query(PhotoRequest)
        .filter(PhotoRequest.customer_id == customer_id)
        .order_by(PhotoRequest.created_at.desc())
        .all()
    )
    return [_request_out(db, r) for r in rows]


@router.get("/customers/{customer_id}/photo-requests/link-options", response_model=PhotoLinkOptionsOut)
def photo_request_link_options(
    customer_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> PhotoLinkOptionsOut:
    """This patient's appointments and treatment enquiries, for linking a new request."""
    require_permission(user, "photo_request.create")
    customer = _get_customer(db, customer_id, user)
    appts = db.query(Appointment).filter(Appointment.customer_id == customer.id).order_by(Appointment.starts_at.desc()).limit(50)
    deals = db.query(Deal).filter(Deal.customer_id == customer.id).order_by(Deal.created_at.desc()).limit(50)
    return PhotoLinkOptionsOut(
        appointments=[
            LinkOption(id=a.id, label=f"{a.starts_at:%d %b %Y %H:%M} · {a.event.name if a.event else a.appointment_type} ({a.status})")
            for a in appts
        ],
        deals=[LinkOption(id=d.id, label=f"{d.treatment_interest or 'Enquiry'} ({d.status})") for d in deals],
    )


@router.post("/customers/{customer_id}/photo-requests", response_model=IssuedLinkOut, status_code=201)
def create_photo_request(
    customer_id: UUID,
    payload: PhotoRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> IssuedLinkOut:
    require_permission(user, "photo_request.create")
    customer = _get_customer(db, customer_id, user)
    if payload.send_email:
        # Fail before anything is created when the patient cannot be emailed.
        emailing.valid_patient_email(customer)
        if customer.can_contact is False:
            raise HTTPException(status_code=422, detail="This patient has opted out of contact, so the link cannot be emailed.")
    if payload.appointment_id is not None:
        appt = db.get(Appointment, payload.appointment_id)
        if appt is None or appt.customer_id != customer.id:
            raise HTTPException(status_code=422, detail="Appointment does not belong to this patient")
    if payload.deal_id is not None:
        deal = db.get(Deal, payload.deal_id)
        if deal is None or deal.customer_id != customer.id:
            raise HTTPException(status_code=422, detail="Treatment enquiry does not belong to this patient")

    req = PhotoRequest(
        customer_id=customer.id,
        appointment_id=payload.appointment_id,
        deal_id=payload.deal_id,
        created_by_user_id=user.id,
        title=payload.title.strip(),
        instructions=(payload.instructions or "").strip() or None,
        status="requested",
        upload_round=1,
    )
    db.add(req)
    db.flush()
    _add_status_event(db, req, "requested", user, None)
    record_audit(
        db,
        actor=user,
        action="photo_request.created",
        entity_type=ENTITY,
        entity_id=req.id,
        after={"status": "requested", "customer_id": str(customer.id)},
        metadata={
            "appointment_id": str(payload.appointment_id) if payload.appointment_id else None,
            "deal_id": str(payload.deal_id) if payload.deal_id else None,
        },
    )
    if payload.send_email:
        try:
            row, _dup, pipeline = _send_link_email(db, req, user, deal_id=payload.deal_id, resend=True)
        except HTTPException:
            # Nothing is kept: no request, no link, no pipeline change.
            db.rollback()
            raise
        db.commit()
        db.refresh(req)
        link = db.get(PhotoAccessLink, row.link_id)
        return IssuedLinkOut(request=_request_out(db, req), link=_link_out(link), email=_email_out(row), pipeline=pipeline)
    link, token = _issue_link(db, req, user)
    db.commit()
    db.refresh(req)
    return IssuedLinkOut(request=_request_out(db, req), link=_link_out(link), portal_url=_portal_url(token))


def _send_link_email(
    db: Session, req: PhotoRequest, user: User, *, deal_id: UUID | None = None, resend: bool = False
) -> tuple[PhotoRequestEmail, bool, dict | None]:
    """Email the patient a fresh link via the outbox; see app.services.photo_request_email."""
    to_email = emailing.check_can_email(req)
    if not resend:
        existing = emailing.existing_live_email(db, req)
        if existing is not None:
            return existing, True, None
    deal = emailing.resolve_deal(db, req, deal_id)
    template = emailing.email_template(db)

    savepoint = db.begin_nested()
    try:
        if deal is not None and req.deal_id != deal.id:
            req.deal_id = deal.id
        link, token = _issue_link(db, req, user)
        name = (req.customer.name or "").strip()
        msg = emailing.queue_outbound_email(
            db,
            customer=req.customer,
            sender=user,
            template=template,
            variables={
                "first_name": name.split(" ")[0] if name else "there",
                "portal_link": _portal_url(token),
                "link_expires": link.expires_at.strftime("%d %B %Y, %H:%M UTC"),
                # The worker keeps these out of the contact thread and wipes them once sent.
                "_redact": ["portal_link"],
            },
        )
        row = PhotoRequestEmail(request_id=req.id, link_id=link.id, outbound_message_id=msg.id, to_email=to_email, sent_by_user_id=user.id)
        db.add(row)
        db.flush()
        pipeline = emailing.advance_pipeline(db, req.customer, user, req.id)
        _touch(req)
        record_audit(
            db,
            actor=user,
            action="photo_request.email_queued",
            entity_type=ENTITY,
            entity_id=req.id,
            metadata={
                "link_id": str(link.id),
                "outbound_message_id": str(msg.id),
                "deal_id": str(req.deal_id) if req.deal_id else None,
                "pipeline": pipeline,
            },
        )
        savepoint.commit()
    except HTTPException:
        savepoint.rollback()
        raise
    except Exception:
        savepoint.rollback()
        logger.exception("Could not queue photo request email")
        raise HTTPException(status_code=503, detail="The email could not be queued, so the request was not sent. Please try again.")
    return row, False, pipeline


@router.post("/photo-requests/{request_id}/send-email", response_model=IssuedLinkOut)
def send_photo_request_email(
    request_id: UUID,
    payload: SendEmailIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> IssuedLinkOut:
    """Email the patient their upload link. Safe to retry: a link whose email is already
    queued or sent is returned as-is (duplicate=true) unless resend is requested."""
    require_permission(user, "photo_request.create")
    req = _get_request(db, request_id, user, lock=True)
    try:
        row, duplicate, pipeline = _send_link_email(db, req, user, deal_id=payload.deal_id, resend=payload.resend)
    except HTTPException as exc:
        db.rollback()
        reason = exc.detail if isinstance(exc.detail, str) else (exc.detail or {}).get("code", "error")
        record_audit(db, actor=user, action="photo_request.email_not_sent", entity_type=ENTITY, entity_id=request_id, metadata={"reason": reason, "status_code": exc.status_code})
        db.commit()
        raise
    db.commit()
    db.refresh(req)
    link = db.get(PhotoAccessLink, row.link_id)
    return IssuedLinkOut(request=_request_out(db, req), link=_link_out(link), email=_email_out(row), duplicate=duplicate, pipeline=pipeline)


@router.get("/photo-requests", response_model=list[PhotoRequestQueueItem])
def photo_request_queue(
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> list[PhotoRequestQueueItem]:
    """Review queue across the patients the caller can access."""
    require_permission(user, "photo_request.view_summary")
    q = db.query(PhotoRequest).join(Customer, Customer.id == PhotoRequest.customer_id)
    if status:
        q = q.filter(PhotoRequest.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    scope = customer_scope(db, user)
    if scope is not None:
        q = q.filter(scope)
    rows = q.order_by(PhotoRequest.updated_at.desc()).limit(limit).all()
    return [PhotoRequestQueueItem(**_request_out(db, r).model_dump(), customer_name=r.customer.name) for r in rows]


@router.get("/photo-requests/{request_id}", response_model=PhotoRequestDetailOut)
def get_photo_request(request_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> PhotoRequestDetailOut:
    require_permission(user, "photo_request.view_summary")
    return _detail(db, _get_request(db, request_id, user), user)


@router.post("/photo-requests/{request_id}/status", response_model=PhotoRequestDetailOut)
def change_status(
    request_id: UUID,
    payload: StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> PhotoRequestDetailOut:
    sources, permission = STAFF_TRANSITIONS[payload.status]
    require_permission(user, permission)
    req = _get_request(db, request_id, user, lock=True)
    if req.status not in sources:
        raise HTTPException(status_code=409, detail=f"Cannot change status from {req.status} to {payload.status}")

    before = {"status": req.status, "upload_round": req.upload_round}
    meta: dict = {"reason_provided": bool(payload.reason)}
    if payload.status == "more_photos_needed":
        message = (payload.patient_message or "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="Tell the patient which photos are needed")
        req.patient_message = message
        req.upload_round += 1
        req.submitted_at = None
    if payload.status == "reviewed":
        has_assessment = db.query(PhotoClinicalAssessment.id).filter(PhotoClinicalAssessment.request_id == req.id).first()
        if not has_assessment:
            raise HTTPException(status_code=409, detail="Add a clinical assessment before marking the request reviewed")
    if payload.status in ("closed", "withdrawn"):
        req.closed_at = now_utc()
        meta["revoked_link_ids"] = [str(i) for i in _revoke_active_links(db, req, user, payload.status)]

    _add_status_event(db, req, payload.status, user, (payload.reason or "").strip() or None)
    req.status = payload.status
    _touch(req)
    record_audit(
        db,
        actor=user,
        action="photo_request.status_changed",
        entity_type=ENTITY,
        entity_id=req.id,
        before=before,
        after={"status": req.status, "upload_round": req.upload_round},
        metadata=meta,
    )
    db.commit()
    db.refresh(req)
    return _detail(db, req, user)


# --- links ---------------------------------------------------------------------


@router.post("/photo-requests/{request_id}/links", response_model=IssuedLinkOut, status_code=201)
def issue_link(request_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> IssuedLinkOut:
    require_permission(user, "photo_request.manage_links")
    req = _get_request(db, request_id, user, lock=True)
    link, token = _issue_link(db, req, user)
    _touch(req)
    db.commit()
    db.refresh(req)
    return IssuedLinkOut(request=_request_out(db, req), link=_link_out(link), portal_url=_portal_url(token))


@router.post("/photo-requests/{request_id}/links/{link_id}/revoke", response_model=PhotoAccessLinkOut)
def revoke_link(
    request_id: UUID,
    link_id: UUID,
    payload: LinkRevokeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> PhotoAccessLinkOut:
    require_permission(user, "photo_request.manage_links")
    req = _get_request(db, request_id, user)
    link = db.get(PhotoAccessLink, link_id)
    if link is None or link.request_id != req.id:
        raise HTTPException(status_code=404, detail="Link not found")
    if link.revoked_at is None:
        link.revoked_at = now_utc()
        link.revoked_by_user_id = user.id
        link.revoke_reason = (payload.reason or "").strip() or "revoked by staff"
        record_audit(db, actor=user, action="photo_request.link_revoked", entity_type=ENTITY, entity_id=req.id, metadata={"link_id": str(link.id)})
        db.commit()
        db.refresh(link)
    return _link_out(link)


# --- photos --------------------------------------------------------------------


def _get_photo(db: Session, req: PhotoRequest, photo_id: UUID) -> PatientPhoto:
    photo = db.get(PatientPhoto, photo_id)
    if photo is None or photo.request_id != req.id:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/photo-requests/{request_id}/photos/{photo_id}/content")
def get_photo_content(
    request_id: UUID,
    photo_id: UUID,
    download: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> StreamingResponse:
    """Authenticated, audited stream of one photo. There is no public URL for photos."""
    require_permission(user, "photo.view")
    req = _get_request(db, request_id, user)
    photo = _get_photo(db, req, photo_id)
    storage = get_photo_storage()
    try:
        size = storage.size(photo.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Photo file is missing from storage")
    record_audit(
        db,
        actor=user,
        action="patient_photo.downloaded" if download else "patient_photo.viewed",
        entity_type=ENTITY,
        entity_id=req.id,
        metadata={"photo_id": str(photo.id)},
    )
    db.commit()
    ext = photo.storage_key.rsplit(".", 1)[-1]
    disposition = "attachment" if download else "inline"
    headers = {
        **PHOTO_RESPONSE_HEADERS,
        "Content-Length": str(size),
        "Content-Disposition": f'{disposition}; filename="photo-{photo.id}.{ext}"',
    }
    return StreamingResponse(storage.iter_bytes(photo.storage_key), media_type=photo.content_type, headers=headers)


@router.post("/photo-requests/{request_id}/photos/{photo_id}/hide", response_model=PatientPhotoOut)
def hide_photo(
    request_id: UUID,
    photo_id: UUID,
    payload: PhotoHideIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> PatientPhotoOut:
    """Soft delete: the photo is flagged, never erased, so the record stays complete."""
    require_permission(user, "photo.hide")
    req = _get_request(db, request_id, user)
    photo = _get_photo(db, req, photo_id)
    if photo.deleted_at is None:
        photo.deleted_at = now_utc()
        photo.deleted_by_user_id = user.id
        photo.delete_reason = payload.reason.strip()
        record_audit(db, actor=user, action="patient_photo.hidden", entity_type=ENTITY, entity_id=req.id, metadata={"photo_id": str(photo.id)})
        db.commit()
        db.refresh(photo)
    return PatientPhotoOut.model_validate(photo)


# --- notes and assessments -----------------------------------------------------


def _create_entry(db: Session, req: PhotoRequest, user: User, model, entry_type: str, body: str):
    body = body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Text is required")
    row = model(
        request_id=req.id,
        author_user_id=user.id,
        author_email=user.email,
        author_role=role_of(user),
        body=body,
        version=1,
    )
    db.add(row)
    db.flush()
    db.add(
        PhotoEntryRevision(
            entry_type=entry_type,
            entry_id=row.id,
            request_id=req.id,
            version=1,
            body=body,
            editor_user_id=user.id,
            editor_email=user.email,
            editor_role=role_of(user),
        )
    )
    # Audit records lengths and versions, not clinical text; the text lives in the revisions table.
    record_audit(
        db,
        actor=user,
        action=f"photo_request.{entry_type}_created",
        entity_type=ENTITY,
        entity_id=req.id,
        after={"version": 1, "length": len(body)},
        metadata={f"{entry_type}_id": str(row.id), "author_role": role_of(user)},
    )
    _touch(req)
    return row


def _update_entry(db: Session, req: PhotoRequest, user: User, row, entry_type: str, body: str):
    if row is None or row.request_id != req.id:
        raise HTTPException(status_code=404, detail="Entry not found")
    if row.author_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit this entry")
    body = body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Text is required")
    before = {"version": row.version, "length": len(row.body)}
    row.version += 1
    row.body = body
    row.updated_at = now_utc()
    db.add(
        PhotoEntryRevision(
            entry_type=entry_type,
            entry_id=row.id,
            request_id=req.id,
            version=row.version,
            body=body,
            editor_user_id=user.id,
            editor_email=user.email,
            editor_role=role_of(user),
        )
    )
    record_audit(
        db,
        actor=user,
        action=f"photo_request.{entry_type}_updated",
        entity_type=ENTITY,
        entity_id=req.id,
        before=before,
        after={"version": row.version, "length": len(body)},
        metadata={f"{entry_type}_id": str(row.id)},
    )
    _touch(req)
    return row


@router.post("/photo-requests/{request_id}/notes", response_model=PhotoRequestDetailOut, status_code=201)
def add_note(request_id: UUID, payload: EntryIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> PhotoRequestDetailOut:
    require_permission(user, "note.write")
    req = _get_request(db, request_id, user)
    _create_entry(db, req, user, PhotoRequestNote, "note", payload.body)
    db.commit()
    return _detail(db, req, user)


@router.patch("/photo-requests/{request_id}/notes/{note_id}", response_model=PhotoRequestDetailOut)
def edit_note(
    request_id: UUID, note_id: UUID, payload: EntryIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> PhotoRequestDetailOut:
    require_permission(user, "note.write")
    req = _get_request(db, request_id, user)
    _update_entry(db, req, user, db.get(PhotoRequestNote, note_id), "note", payload.body)
    db.commit()
    return _detail(db, req, user)


@router.post("/photo-requests/{request_id}/assessments", response_model=PhotoRequestDetailOut, status_code=201)
def add_assessment(
    request_id: UUID, payload: EntryIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> PhotoRequestDetailOut:
    require_permission(user, "assessment.write")
    req = _get_request(db, request_id, user)
    if req.status in ("requested", "withdrawn"):
        raise HTTPException(status_code=409, detail="There are no submitted photos to assess")
    _create_entry(db, req, user, PhotoClinicalAssessment, "assessment", payload.body)
    db.commit()
    return _detail(db, req, user)


@router.patch("/photo-requests/{request_id}/assessments/{assessment_id}", response_model=PhotoRequestDetailOut)
def edit_assessment(
    request_id: UUID,
    assessment_id: UUID,
    payload: EntryIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> PhotoRequestDetailOut:
    require_permission(user, "assessment.write")
    req = _get_request(db, request_id, user)
    _update_entry(db, req, user, db.get(PhotoClinicalAssessment, assessment_id), "assessment", payload.body)
    db.commit()
    return _detail(db, req, user)


def allowed_upload_types() -> tuple[list[str], list[str]]:
    exts: list[str] = []
    mimes: list[str] = []
    for name in settings.photo_allowed_formats:
        spec = FORMATS.get(name)
        if spec:
            exts += sorted(spec["extensions"])
            mimes += sorted(spec["mimes"])
    return exts, mimes
