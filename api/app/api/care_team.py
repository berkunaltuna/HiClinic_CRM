"""Doctor and doctor-assistant interfaces, and admin management of the care team.

Doctors see only patients assigned to them; assistants see the patients of the doctors
they are assigned to (status only, plus proformas); admins see and manage everything.
Assignments are explicit rows, never inferred from names or emails.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_authenticated_user
from app.db.models import (
    AssistantDoctorAssignment,
    Customer,
    Deal,
    DoctorPatientAssignment,
    DoctorProfile,
    PhotoRequest,
    User,
)
from app.db.session import get_db
from app.api.patient_documents import current_proforma
from app.api.photo_requests import _request_out
from app.schemas.photo_request import PhotoRequestOut
from app.services.audit import record_audit
from app.services.photo_permissions import (
    active_doctor_assignment,
    assigned_doctor_ids_for_assistant,
    can_access_customer,
    customer_scope,
    has_permission,
    permissions_for,
    require_permission,
    role_of,
)
from app.services.photo_portal_auth import now_utc

router = APIRouter(prefix="/care", tags=["care-team"])

CARE_ROLES = ("doctor", "doctor_assistant", "admin")


# --- schemas ---------------------------------------------------------------------


class PersonOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None = None


class CareMeOut(BaseModel):
    id: UUID
    email: str
    role: str
    permissions: list[str]
    # For assistants: the doctors they work for.
    doctors: list[PersonOut] = []


class LatestRequestOut(BaseModel):
    id: UUID
    title: str
    status: str
    photo_count: int
    photos_uploaded: bool
    submitted_at: datetime | None = None
    email_status: str | None = None
    updated_at: datetime


class ProformaSummaryOut(BaseModel):
    available: bool
    uploaded_at: datetime | None = None


class CarePatientOut(BaseModel):
    id: UUID
    name: str
    treatment_interest: str | None = None
    doctor: PersonOut | None = None
    open_requests: int
    latest_request: LatestRequestOut | None = None
    # Only for roles that may see proformas (assistant, admin).
    proforma: ProformaSummaryOut | None = None


class CarePatientDetailOut(CarePatientOut):
    requests: list[PhotoRequestOut]


class DoctorAssignmentIn(BaseModel):
    doctor_user_id: UUID | None = None


class AssistantDoctorsIn(BaseModel):
    doctor_user_ids: list[UUID]


class DoctorProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    specialty: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=4000)
    visible_to_patients: bool = False


class DoctorProfileOut(DoctorProfileIn):
    user_id: UUID
    updated_at: datetime | None = None


class DoctorSummaryOut(PersonOut):
    patient_count: int
    assistants: list[PersonOut]
    profile: DoctorProfileOut | None = None


class AssistantSummaryOut(PersonOut):
    doctors: list[PersonOut]


# --- helpers ----------------------------------------------------------------------


def _require_care_role(user: User) -> None:
    if role_of(user) not in CARE_ROLES:
        raise HTTPException(status_code=403, detail="This area is for doctors, assistants and admins")


def _person(db: Session, user: User) -> PersonOut:
    profile = db.get(DoctorProfile, user.id)
    return PersonOut(id=user.id, email=user.email, display_name=profile.display_name if profile else None)


def _patient_out(db: Session, user: User, customer: Customer) -> CarePatientOut:
    requests = db.query(PhotoRequest).filter(PhotoRequest.customer_id == customer.id).order_by(PhotoRequest.updated_at.desc()).all()
    latest = None
    if requests:
        r = _request_out(db, requests[0])
        latest = LatestRequestOut(
            id=r.id,
            title=r.title,
            status=r.status,
            photo_count=r.photo_count,
            # The patient has sent the photos for the current round.
            photos_uploaded=r.submitted_at is not None,
            submitted_at=r.submitted_at,
            email_status=r.email_status,
            updated_at=r.updated_at,
        )
    assignment = active_doctor_assignment(db, customer.id)
    deal = db.query(Deal).filter(Deal.customer_id == customer.id).order_by(Deal.created_at.desc()).first()
    proforma = None
    if has_permission(user, "proforma.view"):
        doc = current_proforma(db, customer.id)
        proforma = ProformaSummaryOut(available=doc is not None, uploaded_at=doc.uploaded_at if doc else None)
    return CarePatientOut(
        id=customer.id,
        name=customer.name,
        treatment_interest=deal.treatment_interest if deal else None,
        doctor=_person(db, assignment.doctor) if assignment else None,
        open_requests=sum(1 for r in requests if r.status not in ("closed", "withdrawn")),
        latest_request=latest,
        proforma=proforma,
    )


def _care_customer(db: Session, user: User, customer_id: UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or not can_access_customer(db, user, customer):
        raise HTTPException(status_code=404, detail="Patient not found")
    return customer


def _user_with_role(db: Session, user_id: UUID, role: str) -> User:
    u = db.get(User, user_id)
    if u is None or role_of(u) != role:
        raise HTTPException(status_code=422, detail=f"That user is not a {role.replace('_', ' ')}")
    return u


# --- doctor / assistant views ------------------------------------------------------


@router.get("/me", response_model=CareMeOut)
def care_me(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> CareMeOut:
    doctors: list[PersonOut] = []
    if role_of(user) == "doctor_assistant":
        doctors = [_person(db, db.get(User, d)) for d in assigned_doctor_ids_for_assistant(db, user.id)]
    return CareMeOut(id=user.id, email=user.email, role=role_of(user), permissions=permissions_for(user), doctors=doctors)


@router.get("/patients", response_model=list[CarePatientOut])
def care_patients(
    status: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
) -> list[CarePatientOut]:
    """Doctor: assigned patients. Assistant: patients of their doctors. Admin: every patient
    with an assigned doctor. Optional status filter on the latest photo request."""
    _require_care_role(user)
    q = db.query(Customer).filter(
        Customer.id.in_(db.query(DoctorPatientAssignment.customer_id).filter(DoctorPatientAssignment.ended_at.is_(None)))
    )
    scope = customer_scope(db, user)
    if scope is not None:
        q = q.filter(scope)
    out = [_patient_out(db, user, c) for c in q.order_by(Customer.name.asc()).limit(500)]
    if status:
        wanted = {s.strip() for s in status.split(",") if s.strip()}
        out = [p for p in out if p.latest_request is not None and p.latest_request.status in wanted]
    return out


@router.get("/patients/{customer_id}", response_model=CarePatientDetailOut)
def care_patient(customer_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> CarePatientDetailOut:
    _require_care_role(user)
    customer = _care_customer(db, user, customer_id)
    base = _patient_out(db, user, customer)
    requests = db.query(PhotoRequest).filter(PhotoRequest.customer_id == customer.id).order_by(PhotoRequest.created_at.desc()).all()
    return CarePatientDetailOut(**base.model_dump(), requests=[_request_out(db, r) for r in requests])


# --- assignments (admin) -------------------------------------------------------------


@router.get("/patients/{customer_id}/doctor", response_model=PersonOut | None)
def get_patient_doctor(customer_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> PersonOut | None:
    """The patient's assigned doctor, for anyone who can see the patient."""
    customer = _care_customer(db, user, customer_id)
    assignment = active_doctor_assignment(db, customer.id)
    return _person(db, assignment.doctor) if assignment else None


@router.put("/patients/{customer_id}/doctor", response_model=PersonOut | None)
def set_patient_doctor(
    customer_id: UUID, payload: DoctorAssignmentIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> PersonOut | None:
    require_permission(user, "care_team.manage")
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    db.query(Customer).filter(Customer.id == customer.id).with_for_update().one()
    current = active_doctor_assignment(db, customer.id)
    new_doctor = _user_with_role(db, payload.doctor_user_id, "doctor") if payload.doctor_user_id else None
    if current is not None and new_doctor is not None and current.doctor_user_id == new_doctor.id:
        return _person(db, new_doctor)
    before = {"doctor_user_id": str(current.doctor_user_id)} if current else None
    if current is not None:
        current.ended_at = now_utc()
        current.ended_by_user_id = user.id
        db.flush()
    if new_doctor is not None:
        db.add(DoctorPatientAssignment(doctor_user_id=new_doctor.id, customer_id=customer.id, assigned_by_user_id=user.id))
    record_audit(
        db,
        actor=user,
        action="care_team.doctor_assigned" if new_doctor else "care_team.doctor_unassigned",
        entity_type="customer",
        entity_id=customer.id,
        before=before,
        after={"doctor_user_id": str(new_doctor.id)} if new_doctor else None,
    )
    db.commit()
    return _person(db, new_doctor) if new_doctor else None


@router.get("/doctors", response_model=list[DoctorSummaryOut])
def list_doctors(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> list[DoctorSummaryOut]:
    require_permission(user, "care_team.manage")
    out = []
    for d in db.query(User).filter(User.role == "doctor").order_by(User.email.asc()):
        count = db.query(DoctorPatientAssignment).filter(DoctorPatientAssignment.doctor_user_id == d.id, DoctorPatientAssignment.ended_at.is_(None)).count()
        assistant_ids = [
            r[0]
            for r in db.query(AssistantDoctorAssignment.assistant_user_id).filter(
                AssistantDoctorAssignment.doctor_user_id == d.id, AssistantDoctorAssignment.ended_at.is_(None)
            )
        ]
        profile = db.get(DoctorProfile, d.id)
        out.append(
            DoctorSummaryOut(
                **_person(db, d).model_dump(),
                patient_count=count,
                assistants=[_person(db, db.get(User, a)) for a in assistant_ids],
                profile=_profile_out(profile) if profile else None,
            )
        )
    return out


@router.get("/assistants", response_model=list[AssistantSummaryOut])
def list_assistants(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)) -> list[AssistantSummaryOut]:
    require_permission(user, "care_team.manage")
    return [
        AssistantSummaryOut(
            **_person(db, a).model_dump(),
            doctors=[_person(db, db.get(User, d)) for d in assigned_doctor_ids_for_assistant(db, a.id)],
        )
        for a in db.query(User).filter(User.role == "doctor_assistant").order_by(User.email.asc())
    ]


@router.put("/assistants/{assistant_id}/doctors", response_model=AssistantSummaryOut)
def set_assistant_doctors(
    assistant_id: UUID, payload: AssistantDoctorsIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> AssistantSummaryOut:
    require_permission(user, "care_team.manage")
    assistant = _user_with_role(db, assistant_id, "doctor_assistant")
    wanted = {d.id for d in (_user_with_role(db, i, "doctor") for i in set(payload.doctor_user_ids))}
    current = {
        a.doctor_user_id: a
        for a in db.query(AssistantDoctorAssignment).filter(
            AssistantDoctorAssignment.assistant_user_id == assistant.id, AssistantDoctorAssignment.ended_at.is_(None)
        )
    }
    for doctor_id, row in current.items():
        if doctor_id not in wanted:
            row.ended_at = now_utc()
            row.ended_by_user_id = user.id
    for doctor_id in wanted - current.keys():
        db.add(AssistantDoctorAssignment(assistant_user_id=assistant.id, doctor_user_id=doctor_id, assigned_by_user_id=user.id))
    record_audit(
        db,
        actor=user,
        action="care_team.assistant_doctors_set",
        entity_type="user",
        entity_id=assistant.id,
        before={"doctor_user_ids": sorted(str(i) for i in current)},
        after={"doctor_user_ids": sorted(str(i) for i in wanted)},
    )
    db.commit()
    return AssistantSummaryOut(**_person(db, assistant).model_dump(), doctors=[_person(db, db.get(User, d)) for d in sorted(wanted, key=str)])


def _profile_out(p: DoctorProfile) -> DoctorProfileOut:
    return DoctorProfileOut(
        user_id=p.user_id,
        display_name=p.display_name,
        title=p.title,
        specialty=p.specialty,
        bio=p.bio,
        visible_to_patients=p.visible_to_patients,
        updated_at=p.updated_at,
    )


@router.put("/doctors/{doctor_id}/profile", response_model=DoctorProfileOut)
def set_doctor_profile(
    doctor_id: UUID, payload: DoctorProfileIn, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)
) -> DoctorProfileOut:
    """What patients see about this doctor. Only admins edit it; empty fields are not shown."""
    require_permission(user, "care_team.manage")
    doctor = _user_with_role(db, doctor_id, "doctor")
    profile = db.get(DoctorProfile, doctor.id) or DoctorProfile(user_id=doctor.id)
    before = _profile_out(profile).model_dump(mode="json") if profile.updated_at else None
    for field in ("display_name", "title", "specialty", "bio"):
        value = getattr(payload, field)
        setattr(profile, field, value.strip() if value and value.strip() else None)
    profile.visible_to_patients = payload.visible_to_patients
    profile.updated_by_user_id = user.id
    profile.updated_at = now_utc()
    db.add(profile)
    db.flush()
    record_audit(
        db,
        actor=user,
        action="care_team.doctor_profile_updated",
        entity_type="user",
        entity_id=doctor.id,
        before=before,
        after=_profile_out(profile).model_dump(mode="json"),
    )
    db.commit()
    return _profile_out(profile)
