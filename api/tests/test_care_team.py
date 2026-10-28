"""Doctor and assistant interfaces, assignments, photo-request emails, pipeline, proformas."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute

from accounts import DEFAULT_PASSWORD, staff_token
from app.core.config import settings
from app.db.models import (
    AuditLog,
    Customer,
    Deal,
    OutboundMessage,
    PatientDocument,
    PhotoAccessLink,
    PhotoRequest,
    PhotoRequestEmail,
)
from app.main import app
from app.services import photo_request_email as emailing
from app.services import photo_storage
from app.services.photo_portal_auth import failed_attempts

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"0" * 300 + b"\n%%EOF\n"


@pytest.fixture(autouse=True)
def _reset_limiter():
    failed_attempts.reset()
    yield


# --- helpers ---------------------------------------------------------------------


def staff(client, role: str) -> dict:
    email = f"{role}_{uuid.uuid4().hex[:8]}@example.com"
    return {"Authorization": f"Bearer {staff_token(client, email, role=role)}"}


def uid(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["id"]


def patient(client, headers, name="Ayse Patient", email="patient@example.com", stage=None) -> str:
    r = client.post("/customers", json={"name": name, "email": email, "phone": None, "company": None, "next_follow_up_at": None}, headers=headers)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    if stage:
        assert client.post(f"/inbox/customers/{cid}/stage", json={"stage": stage}, headers=headers).status_code == 204
    return cid


def assign(client, admin, cid, doctor) -> None:
    r = client.put(f"/care/patients/{cid}/doctor", json={"doctor_user_id": uid(client, doctor)}, headers=admin)
    assert r.status_code == 200, r.text


def assign_assistant(client, admin, assistant, *doctors) -> None:
    r = client.put(f"/care/assistants/{uid(client, assistant)}/doctors", json={"doctor_user_ids": [uid(client, d) for d in doctors]}, headers=admin)
    assert r.status_code == 200, r.text


def new_request(client, headers, cid, **extra) -> dict:
    r = client.post(f"/customers/{cid}/photo-requests", json={"title": "Hair assessment", "instructions": "Front and top.", **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def portal_session(client, portal_url: str) -> dict:
    token = portal_url.split("#token=", 1)[1]
    r = client.post("/portal/photo-request/session", json={"token": token})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def queued_link(db, request_id) -> str:
    """The portal link inside the queued outbox email (what the patient receives)."""
    db.expire_all()
    row = db.query(PhotoRequestEmail).filter(PhotoRequestEmail.request_id == uuid.UUID(request_id)).order_by(PhotoRequestEmail.created_at.desc()).first()
    return db.get(OutboundMessage, row.outbound_message_id).variables["portal_link"]


def upload_and_submit(client, ph) -> None:
    assert client.post("/portal/photo-request/consent", json={"version": settings.photo_consent_version, "accepted": True}, headers=ph).status_code == 204
    r = client.put("/portal/photo-request/photos", params={"filename": "a.jpg"}, content=JPEG, headers={**ph, "Content-Type": "image/jpeg"})
    assert r.status_code == 201, r.text
    assert client.post("/portal/photo-request/submit", headers=ph).status_code == 200


def put_proforma(client, headers, cid, data=PDF, filename="proforma.pdf", ctype="application/pdf"):
    return client.put(f"/customers/{cid}/proforma", params={"filename": filename}, content=data, headers={**headers, "Content-Type": ctype})


def audits(db, **filters) -> list[str]:
    db.expire_all()
    q = db.query(AuditLog)
    for k, v in filters.items():
        q = q.filter(getattr(AuditLog, k) == (uuid.UUID(v) if k == "entity_id" else v))
    return [a.action for a in q]


@pytest.fixture()
def team(client, admin_headers):
    """Two doctors, an assistant for doctor A, a coordinator, and one patient per doctor."""
    coord = staff(client, "coordinator")
    doc_a, doc_b = staff(client, "doctor"), staff(client, "doctor")
    assistant = staff(client, "doctor_assistant")
    pa = patient(client, coord, "Patient Alpha", "alpha@example.com")
    pb = patient(client, coord, "Patient Beta", "beta@example.com")
    assign(client, admin_headers, pa, doc_a)
    assign(client, admin_headers, pb, doc_b)
    assign_assistant(client, admin_headers, assistant, doc_a)
    return {"admin": admin_headers, "coord": coord, "doc_a": doc_a, "doc_b": doc_b, "assistant": assistant, "pa": pa, "pb": pb}


# --- 1. doctors are kept out of the CRM ------------------------------------------------

CARE_ALLOWED_PREFIXES = ("/auth", "/care", "/photo-requests", "/portal", "/health", "/customers/{customer_id}/photo-requests", "/customers/{customer_id}/proforma")


def _concrete(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_doctor_sees_only_assigned_patients_and_no_crm_routes(client, team):
    doc = team["doc_a"]
    ids = [p["id"] for p in client.get("/care/patients", headers=doc).json()]
    assert ids == [team["pa"]]

    # Every authenticated GET route of the general CRM refuses doctors and assistants.
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods or route.path.startswith(CARE_ALLOWED_PREFIXES):
            continue
        path = _concrete(route.path)
        if client.get(path).status_code != 401:
            continue  # public route (webhooks, health)
        for who in ("doc_a", "assistant"):
            assert client.get(path, headers=team[who]).status_code == 403, (who, route.path)
        checked += 1
    assert checked >= 20

    # Contacts, deals, users, templates and audit logs specifically.
    for path in ("/customers", f"/customers/{team['pa']}", f"/customers/{team['pa']}/deals", "/users", "/templates", "/events", "/audit-logs", "/outbound-messages"):
        assert client.get(path, headers=doc).status_code == 403, path
    # The care-team admin endpoints are admin-only too.
    assert client.get("/care/doctors", headers=doc).status_code == 403
    assert client.put(f"/care/patients/{team['pb']}/doctor", json={"doctor_user_id": uid(client, doc)}, headers=doc).status_code == 403


# --- 2. doctors cannot reach another doctor's patients -----------------------------------


def test_doctor_cannot_see_another_doctors_patients(client, db, team):
    issued = new_request(client, team["doc_b"], team["pb"])
    rid = issued["request"]["id"]
    ph = portal_session(client, issued["portal_url"])
    upload_and_submit(client, ph)
    photo_id = client.get(f"/photo-requests/{rid}", headers=team["doc_b"]).json()["photos"][0]["id"]
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "B's assessment"}, headers=team["doc_b"]).status_code == 201

    a = team["doc_a"]
    assert client.get(f"/care/patients/{team['pb']}", headers=a).status_code == 404
    assert client.get(f"/photo-requests/{rid}", headers=a).status_code == 404
    assert client.get(f"/photo-requests/{rid}/photos/{photo_id}/content", headers=a).status_code == 404
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "x"}, headers=a).status_code == 404
    assert client.get(f"/customers/{team['pb']}/photo-requests", headers=a).status_code == 404
    assert client.post(f"/customers/{team['pb']}/photo-requests", json={"title": "x"}, headers=a).status_code == 404
    assert rid not in [q["id"] for q in client.get("/photo-requests", headers=a).json()]


# --- 3. assistants see status only ----------------------------------------------------------


def test_assistant_sees_status_but_no_clinical_content(client, team):
    issued = new_request(client, team["doc_a"], team["pa"])
    rid = issued["request"]["id"]
    asst = team["assistant"]
    rows = client.get("/care/patients", headers=asst).json()
    assert [p["id"] for p in rows] == [team["pa"]]
    assert rows[0]["latest_request"]["status"] == "requested" and rows[0]["latest_request"]["photos_uploaded"] is False

    upload_and_submit(client, portal_session(client, issued["portal_url"]))
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "CLINICAL-SECRET"}, headers=team["doc_a"]).status_code == 201
    row = client.get("/care/patients", headers=asst).json()[0]
    assert row["latest_request"]["status"] == "uploaded" and row["latest_request"]["photos_uploaded"] is True

    detail = client.get(f"/photo-requests/{rid}", headers=asst)
    assert detail.status_code == 200
    d = detail.json()
    assert d["photos"] is None and d["assessments"] is None and d["notes"] is None
    assert "CLINICAL-SECRET" not in detail.text
    assert client.get(f"/care/patients/{team['pb']}", headers=asst).status_code == 404
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "x"}, headers=asst).status_code == 403
    assert client.post(f"/photo-requests/{rid}/notes", json={"body": "x"}, headers=asst).status_code == 403
    assert client.post(f"/customers/{team['pa']}/photo-requests", json={"title": "x"}, headers=asst).status_code == 403


# --- 4. assistants manage proformas for their doctor's patients only --------------------------


def test_assistant_proformas_scoped_to_their_doctor(client, db, team):
    asst = team["assistant"]
    r = put_proforma(client, asst, team["pa"])
    assert r.status_code == 201, r.text
    first = r.json()["id"]
    r = client.get(f"/customers/{team['pa']}/proforma/{first}/content", headers=asst)
    assert r.status_code == 200 and r.content == PDF and r.headers["cache-control"].startswith("no-store")

    # Replacing supersedes (keeps) the old file.
    r = put_proforma(client, asst, team["pa"], data=PDF + b"v2")
    assert r.status_code == 201
    info = client.get(f"/customers/{team['pa']}/proforma", headers=asst).json()
    assert info["current"]["id"] == r.json()["id"] and len(info["history"]) == 2
    assert info["history"][1]["superseded_at"] is not None

    # Another doctor's patient: nothing, whatever the IDs.
    assert put_proforma(client, asst, team["pb"]).status_code == 404
    assert client.get(f"/customers/{team['pb']}/proforma", headers=asst).status_code == 404
    other = put_proforma(client, team["admin"], team["pb"]).json()["id"]
    assert client.get(f"/customers/{team['pb']}/proforma/{other}/content", headers=asst).status_code == 404
    assert client.get(f"/customers/{team['pa']}/proforma/{other}/content", headers=asst).status_code == 404
    # Doctors don't handle proformas.
    assert client.get(f"/customers/{team['pa']}/proforma", headers=team["doc_a"]).status_code == 403


# --- 5. admins see and manage everything --------------------------------------------------------


def test_admin_manages_assignments_profiles_requests_and_proformas(client, db, team):
    admin = team["admin"]
    doctors = {d["id"]: d for d in client.get("/care/doctors", headers=admin).json()}
    a_id = uid(client, team["doc_a"])
    assert doctors[a_id]["patient_count"] == 1 and [x["id"] for x in doctors[a_id]["assistants"]] == [uid(client, team["assistant"])]
    assert {p["id"] for p in client.get("/care/patients", headers=admin).json()} >= {team["pa"], team["pb"]}

    # Reassign Alpha to doctor B: A loses access, B gains it; history is kept.
    assign(client, admin, team["pa"], team["doc_b"])
    assert client.get(f"/care/patients/{team['pa']}", headers=team["doc_a"]).status_code == 404
    assert client.get(f"/care/patients/{team['pa']}", headers=team["doc_b"]).status_code == 200
    assert client.get(f"/care/patients/{team['pa']}", headers=team["assistant"]).status_code == 404
    # Assignments only accept the right roles.
    assert client.put(f"/care/patients/{team['pa']}/doctor", json={"doctor_user_id": uid(client, team["coord"])}, headers=admin).status_code == 422
    r = client.put(f"/care/assistants/{uid(client, team['assistant'])}/doctors", json={"doctor_user_ids": [uid(client, team["coord"])]}, headers=admin)
    assert r.status_code == 422

    r = client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "Dr. A", "specialty": "Hair restoration", "visible_to_patients": True}, headers=admin)
    assert r.status_code == 200 and r.json()["display_name"] == "Dr. A"
    issued = new_request(client, admin, team["pb"])
    assert client.get(f"/photo-requests/{issued['request']['id']}", headers=admin).status_code == 200
    assert put_proforma(client, admin, team["pb"]).status_code == 201
    assert client.get(f"/customers/{team['pb']}/proforma", headers=admin).json()["current"] is not None
    # Non-admins cannot manage profiles.
    assert client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "x"}, headers=team["coord"]).status_code == 403


# --- 6 + 7. who can request, and exactly one email ----------------------------------------------


def test_crm_user_and_doctor_can_request_photos_by_email_once(client, db, team):
    # Coordinator from the CRM contact; doctor from the doctor interface.
    for who in ("coord", "doc_a"):
        out = new_request(client, team[who], team["pa"], send_email=True)
        assert out["portal_url"] is None and out["email"]["status"] == "queued" and out["email"]["to_email"] == "alpha@example.com"
        rid = out["request"]["id"]
        assert out["request"]["email_status"] == "queued"

        # The queued email carries a working link scoped to exactly this request.
        link = queued_link(db, rid)
        assert link.startswith(settings.frontend_base_url) and "#token=pr_" in link
        ph = portal_session(client, link)
        assert client.get("/portal/photo-request", headers=ph).json()["title"] == "Hair assessment"

        # Retrying does not send again.
        for _ in range(2):
            r = client.post(f"/photo-requests/{rid}/send-email", json={}, headers=team[who])
            assert r.status_code == 200 and r.json()["duplicate"] is True
        db.expire_all()
        assert db.query(PhotoRequestEmail).filter(PhotoRequestEmail.request_id == uuid.UUID(rid)).count() == 1
        msgs = db.query(OutboundMessage).filter(OutboundMessage.customer_id == uuid.UUID(team["pa"])).count()

        # An explicit resend sends one new email with a new link and revokes the old one.
        r = client.post(f"/photo-requests/{rid}/send-email", json={"resend": True}, headers=team[who])
        assert r.status_code == 200 and r.json()["duplicate"] is False
        db.expire_all()
        assert db.query(OutboundMessage).filter(OutboundMessage.customer_id == uuid.UUID(team["pa"])).count() == msgs + 1
        assert client.post("/portal/photo-request/session", json={"token": link.split("#token=")[1]}).status_code == 401

    # The outbox API never shows the link.
    listing = client.get("/outbound-messages", headers=team["coord"]).text
    assert "#token=pr_" not in listing and "[hidden]" in listing
    # The default "user" role cannot request photos.
    assert client.post(f"/customers/{team['pa']}/photo-requests", json={"title": "x", "send_email": True}, headers=staff(client, "user")).status_code == 403


def test_worker_redacts_secret_variables():
    for candidate in (Path(__file__).resolve().parents[2] / "worker" / "app" / "redaction.py", Path("/worker/app/redaction.py")):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("worker_redaction", candidate)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            break
    else:
        pytest.skip("worker source not mounted")
    secret = {"first_name": "Ayse", "portal_link": "https://x/portal/photos#token=pr_secret", "_redact": ["portal_link"]}
    out = mod.redact_variables(secret)
    assert out["portal_link"] == mod.REDACTED_VALUE and out["first_name"] == "Ayse" and "pr_secret" not in str(out)
    plain = {"first_name": "Ayse"}
    assert mod.redact_variables(plain) is plain


# --- 8. failures are reported and change nothing -------------------------------------------------


def test_missing_email_or_queue_failure_is_reported_and_changes_nothing(client, db, team, monkeypatch):
    coord, admin = team["coord"], team["admin"]
    no_email = patient(client, coord, "No Email", email=None, stage="interested")
    before = db.query(PhotoRequest).count()
    r = client.post(f"/customers/{no_email}/photo-requests", json={"title": "x", "send_email": True}, headers=coord)
    assert r.status_code == 422 and "no email" in r.json()["detail"].lower()
    db.expire_all()
    assert db.query(PhotoRequest).count() == before
    assert db.get(Customer, uuid.UUID(no_email)).stage == "interested"

    # Invalid address on an existing request.
    rid = new_request(client, coord, team["pa"])["request"]["id"]
    db.query(Customer).filter(Customer.id == uuid.UUID(team["pa"])).update({Customer.email: "broken@@example"})
    db.commit()
    assert client.post(f"/photo-requests/{rid}/send-email", json={}, headers=coord).status_code == 422
    db.query(Customer).filter(Customer.id == uuid.UUID(team["pa"])).update({Customer.email: "alpha@example.com", Customer.stage: "interested"})
    db.commit()

    # The outbox refuses the message: 503, nothing recorded as sent, pipeline unchanged.
    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(emailing, "queue_outbound_email", boom)
    links_before = db.query(PhotoAccessLink).filter(PhotoAccessLink.request_id == uuid.UUID(rid), PhotoAccessLink.revoked_at.is_(None)).count()
    r = client.post(f"/photo-requests/{rid}/send-email", json={}, headers=coord)
    assert r.status_code == 503 and "not sent" in r.json()["detail"]
    db.expire_all()
    assert db.query(PhotoRequestEmail).filter(PhotoRequestEmail.request_id == uuid.UUID(rid)).count() == 0
    assert db.get(Customer, uuid.UUID(team["pa"])).stage == "interested"
    assert db.query(PhotoAccessLink).filter(PhotoAccessLink.request_id == uuid.UUID(rid), PhotoAccessLink.revoked_at.is_(None)).count() == links_before
    assert client.get(f"/photo-requests/{rid}", headers=coord).json()["request"]["email_status"] is None
    assert "photo_request.email_not_sent" in audits(db, entity_id=rid)

    # Opted-out patients are not emailed.
    monkeypatch.undo()
    db.query(Customer).filter(Customer.id == uuid.UUID(team["pa"])).update({Customer.can_contact: False})
    db.commit()
    assert client.post(f"/photo-requests/{rid}/send-email", json={}, headers=coord).status_code == 422


# --- 9. only the relevant case moves, forward only --------------------------------------------


def test_queued_request_moves_only_the_patients_case_forward(client, db, team):
    coord = team["coord"]
    cid = patient(client, coord, "Two Enquiries", "two@example.com", stage="contacted")
    for t in ("Hair", "Teeth"):
        assert client.post(f"/customers/{cid}/deals", json={"amount": 0, "treatment_interest": t}, headers=coord).status_code == 201
    other = patient(client, coord, "Untouched", "untouched@example.com", stage="contacted")
    rid = new_request(client, coord, cid)["request"]["id"]

    # Ambiguous: two open enquiries and none chosen -> staff must pick; nothing changes.
    r = client.post(f"/photo-requests/{rid}/send-email", json={}, headers=coord)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "deal_selection_required" and len(r.json()["detail"]["deals"]) == 2
    db.expire_all()
    assert db.get(Customer, uuid.UUID(cid)).stage == "contacted"

    deal_id = r.json()["detail"]["deals"][1]["id"]
    deal_status_before = {str(d.id): d.status for d in db.query(Deal).filter(Deal.customer_id == uuid.UUID(cid))}
    r = client.post(f"/photo-requests/{rid}/send-email", json={"deal_id": deal_id}, headers=coord)
    assert r.status_code == 200 and r.json()["pipeline"]["changed"] is True
    db.expire_all()
    assert db.get(Customer, uuid.UUID(cid)).stage == "photos_requested"
    assert db.get(PhotoRequest, uuid.UUID(rid)).deal_id == uuid.UUID(deal_id)
    assert {str(d.id): d.status for d in db.query(Deal).filter(Deal.customer_id == uuid.UUID(cid))} == deal_status_before
    assert db.get(Customer, uuid.UUID(other)).stage == "contacted"
    assert "pipeline.stage_changed" in audits(db, entity_id=cid)

    # A later-stage case is never moved backwards.
    late = patient(client, coord, "Deposit Paid", "late@example.com", stage="deposit_paid")
    r = client.post(f"/customers/{late}/photo-requests", json={"title": "x", "send_email": True}, headers=coord)
    assert r.status_code == 201 and r.json()["pipeline"]["changed"] is False
    db.expire_all()
    assert db.get(Customer, uuid.UUID(late)).stage == "deposit_paid"


# --- 10 + 11. uploads show up for everyone; the portal shows only what it should -----------------


def test_upload_status_visible_by_role_and_portal_contents(client, db, team):
    admin, doc = team["admin"], team["doc_a"]
    db.query(Customer).filter(Customer.id == uuid.UUID(team["pa"])).update({Customer.stage: "deposit_requested"})
    db.commit()
    issued = new_request(client, doc, team["pa"])
    rid = issued["request"]["id"]
    ph = portal_session(client, issued["portal_url"])
    assert client.post(f"/photo-requests/{rid}/notes", json={"body": "STAFF-NOTE-ZZZ"}, headers=doc).status_code == 201

    # Before anything exists: clear empty states.
    body = client.get("/portal/photo-request", headers=ph).json()
    assert body["proforma"] == {"available": False, "filename": None, "uploaded_at": None}
    assert body["doctor"] is None
    assert client.post("/portal/photo-request/proforma/link", headers=ph).status_code == 404

    upload_and_submit(client, ph)
    for who in ("doc_a", "assistant", "admin"):
        row = next(p for p in client.get("/care/patients", headers=team[who]).json() if p["id"] == team["pa"])
        assert row["latest_request"]["status"] == "uploaded" and row["latest_request"]["photos_uploaded"] is True, who
    assert client.get(f"/customers/{team['pa']}/photo-requests", headers=team["coord"]).json()[0]["status"] == "uploaded"
    db.expire_all()
    assert db.get(Customer, uuid.UUID(team["pa"])).stage == "deposit_requested"  # upload never moves the case

    # Profile hidden until an admin fills it in and makes it visible; no invented fields.
    a_id = uid(client, doc)
    client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "Dr. Alpha", "visible_to_patients": False}, headers=admin)
    assert client.get("/portal/photo-request", headers=ph).json()["doctor"] is None
    client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "Dr. Alpha", "specialty": "Hair restoration", "visible_to_patients": True}, headers=admin)
    assert put_proforma(client, team["assistant"], team["pa"]).status_code == 201
    r = client.get("/portal/photo-request", headers=ph)
    body = r.json()
    assert body["doctor"] == {"display_name": "Dr. Alpha", "title": None, "specialty": "Hair restoration", "bio": None}
    assert body["proforma"]["available"] is True
    for secret in ("STAFF-NOTE-ZZZ", "alpha@example.com", "Patient Beta", '"notes"', '"assessments"', "doctor_user_id", "@example.com"):
        assert secret not in r.text

    # The patient opens their proforma through a short-lived link.
    link = client.post("/portal/photo-request/proforma/link", headers=ph).json()
    assert link["url"].startswith("/portal/photo-request/proforma/content?token=")
    r = client.get(link["url"])
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"].startswith("no-store")
    assert "patient_document.viewed_by_patient" in audits(db, action="patient_document.viewed_by_patient")


# --- 12. rejected access ---------------------------------------------------------------------------


def test_document_and_cross_patient_access_rejected(client, db, team, monkeypatch):
    asst = team["assistant"]
    doc_a = put_proforma(client, asst, team["pa"]).json()["id"]
    doc_b = put_proforma(client, team["admin"], team["pb"]).json()["id"]
    ia, ib = new_request(client, team["doc_a"], team["pa"]), new_request(client, team["doc_b"], team["pb"])
    pha, phb = portal_session(client, ia["portal_url"]), portal_session(client, ib["portal_url"])

    # No auth / wrong token types.
    assert client.get(f"/customers/{team['pa']}/proforma/{doc_a}/content").status_code == 401
    assert client.get(f"/customers/{team['pa']}/proforma/{doc_a}/content", headers=pha).status_code == 401
    assert client.get("/portal/photo-request/proforma/content", params={"token": "garbage"}).status_code == 401
    staff_jwt = asst["Authorization"].split(" ", 1)[1]
    assert client.get("/portal/photo-request/proforma/content", params={"token": staff_jwt}).status_code == 401
    assert client.get("/portal/photo-request/proforma/content", params={"token": pha["Authorization"].split(" ", 1)[1]}).status_code == 401

    # Each patient's link opens only their own proforma.
    url_a = client.post("/portal/photo-request/proforma/link", headers=pha).json()["url"]
    url_b = client.post("/portal/photo-request/proforma/link", headers=phb).json()["url"]
    assert client.get(url_a).content == PDF and client.get(url_b).status_code == 200
    # Tampering with the token breaks it.
    tok = url_a.split("token=", 1)[1]
    assert client.get("/portal/photo-request/proforma/content", params={"token": tok[:-2] + ("AA" if tok[-2:] != "AA" else "BB")}).status_code == 401

    # Superseded documents and revoked portal links stop old links working.
    put_proforma(client, asst, team["pa"], data=PDF + b"new")
    assert client.get(url_a).status_code == 401
    link_id = ia["link"]["id"]
    url_a2 = client.post("/portal/photo-request/proforma/link", headers=pha).json()["url"]
    assert client.post(f"/photo-requests/{ia['request']['id']}/links/{link_id}/revoke", json={}, headers=team["doc_a"]).status_code == 200
    assert client.get(url_a2).status_code == 401

    # Expired document links.
    monkeypatch.setattr(settings, "portal_document_link_seconds", -5)
    expired = client.post("/portal/photo-request/proforma/link", headers=phb).json()["url"]
    assert client.get(expired).status_code == 401

    # Altered IDs on staff routes.
    assert client.get(f"/customers/{team['pa']}/proforma/{doc_b}/content", headers=team["admin"]).status_code == 404
    assert client.get(f"/customers/{uuid.uuid4()}/proforma", headers=asst).status_code == 404


# --- 13. validation, private storage, streaming --------------------------------------------------


def test_proforma_validation_storage_and_streaming(client, db, team, monkeypatch):
    asst, cid = team["assistant"], team["pa"]
    assert put_proforma(client, asst, cid, data=JPEG, filename="p.jpg", ctype="image/jpeg").status_code == 415
    assert put_proforma(client, asst, cid, data=JPEG, filename="p.pdf").status_code == 415  # spoofed
    assert put_proforma(client, asst, cid, data=b"<html>not a pdf</html>" * 3, filename="p.pdf").status_code == 415
    assert put_proforma(client, asst, cid, data=PDF, filename="p.pdf", ctype="image/png").status_code == 415
    monkeypatch.setattr(settings, "proforma_max_file_size_mb", 1)
    assert put_proforma(client, asst, cid, data=PDF + b"0" * (1024 * 1024)).status_code == 413

    doc_id = put_proforma(client, asst, cid).json()["id"]
    doc = db.get(PatientDocument, uuid.UUID(doc_id))
    path = Path(settings.photo_storage_dir) / doc.storage_key
    assert path.exists() and (path.stat().st_mode & 0o077) == 0
    assert "alpha" not in doc.storage_key.lower() and "proforma" not in doc.storage_key
    for public in (f"/{doc.storage_key}", f"/static/{doc.storage_key}", f"/documents/{doc.storage_key}"):
        assert client.get(public).status_code in (404, 405)

    # Streamed in chunks, never read whole.
    from starlette.requests import Request

    async def _no_body(self):  # pragma: no cover
        raise AssertionError("upload read the full body into memory")

    monkeypatch.setattr(Request, "body", _no_body)
    writes: list[int] = []
    real_open = photo_storage.LocalPhotoStorage.open_writer

    def spy_open(self):
        w = real_open(self)
        orig = w.write

        def write(chunk):
            writes.append(len(chunk))
            orig(chunk)

        w.write = write
        return w

    monkeypatch.setattr(photo_storage.LocalPhotoStorage, "open_writer", spy_open)
    chunk, n = 64 * 1024, 12

    async def body():
        yield PDF[:16] + b"0" * (chunk - 16)
        for _ in range(n - 1):
            yield b"0" * chunk

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.put(
                f"/customers/{cid}/proforma",
                params={"filename": "big.pdf"},
                content=body(),
                headers={**asst, "Content-Type": "application/pdf", "Content-Length": str(n * chunk)},
            )

    r = asyncio.run(run())
    assert r.status_code == 201, r.text
    assert len(writes) >= n and max(writes) <= chunk


# --- 14. audit trail ----------------------------------------------------------------------------------


def test_care_team_audit_records(client, db, team):
    admin, asst = team["admin"], team["assistant"]
    a_id = uid(client, team["doc_a"])
    client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "Dr. Audit", "visible_to_patients": True}, headers=admin)
    out = new_request(client, team["doc_a"], team["pa"], send_email=True)
    doc1 = put_proforma(client, asst, team["pa"]).json()["id"]
    doc2 = put_proforma(client, asst, team["pa"], data=PDF + b"2").json()["id"]
    client.get(f"/customers/{team['pa']}/proforma/{doc2}/content", headers=asst)
    client.get(f"/customers/{team['pa']}/proforma/{doc2}/content?download=true", headers=admin)
    ph = portal_session(client, queued_link(db, out["request"]["id"]))
    client.get(client.post("/portal/photo-request/proforma/link", headers=ph).json()["url"])

    assert "care_team.doctor_assigned" in audits(db, entity_id=team["pa"])
    assert "care_team.assistant_doctors_set" in audits(db, entity_id=uid(client, asst))
    assert "care_team.doctor_profile_updated" in audits(db, entity_id=a_id)
    req_actions = audits(db, entity_id=out["request"]["id"])
    for a in ("photo_request.created", "photo_request.link_issued", "photo_request.email_queued", "photo_portal.session_opened"):
        assert a in req_actions, a
    assert audits(db, entity_id=doc1) == ["patient_document.uploaded"]
    d2 = audits(db, entity_id=doc2)
    for a in ("patient_document.replaced", "patient_document.viewed", "patient_document.downloaded", "patient_document.viewed_by_patient"):
        assert a in d2, a
    assert "patient_document.link_issued_to_patient" in audits(db, action="patient_document.link_issued_to_patient")
    # The secret link is never in the audit trail.
    db.expire_all()
    assert not [a for a in db.query(AuditLog) if "pr_" in str(a.meta or "") + str(a.after or "")]


def test_role_change_ends_care_team_assignments(client, db, team):
    admin = team["admin"]
    a_id = uid(client, team["doc_a"])
    client.put(f"/care/doctors/{a_id}/profile", json={"display_name": "Dr. Gone", "visible_to_patients": True}, headers=admin)
    issued = new_request(client, team["coord"], team["pa"])
    ph = portal_session(client, issued["portal_url"])
    assert client.get("/portal/photo-request", headers=ph).json()["doctor"]["display_name"] == "Dr. Gone"

    assert client.patch(f"/users/{a_id}", json={"role": "coordinator"}, headers=admin).status_code == 200
    assert client.get("/portal/photo-request", headers=ph).json()["doctor"] is None
    assert client.get(f"/care/patients/{team['pa']}/doctor", headers=admin).json() is None
    assert client.get("/care/patients", headers=team["assistant"]).json() == []
    assert "user.updated" in audits(db, entity_id=a_id)


# --- explicit checks: pipeline on queue success/failure, assistant file access ---------------


def test_pipeline_moves_only_on_successful_queue_including_create(client, db, team, monkeypatch):
    """Create + email: success moves this patient's case to Photos Requested; a queue failure
    keeps nothing (no request, no email, no link) and leaves every case where it was."""
    coord = team["coord"]
    target = patient(client, coord, "Queue Target", "target@example.com", stage="interested")
    bystander = patient(client, coord, "Bystander", "bystander@example.com", stage="interested")
    deal = client.post(f"/customers/{target}/deals", json={"amount": 0, "treatment_interest": "Hair"}, headers=coord).json()

    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(emailing, "queue_outbound_email", boom)
    requests_before = db.query(PhotoRequest).filter(PhotoRequest.customer_id == uuid.UUID(target)).count()
    r = client.post(f"/customers/{target}/photo-requests", json={"title": "x", "send_email": True}, headers=coord)
    assert r.status_code == 503 and "not sent" in r.json()["detail"]
    db.expire_all()
    assert db.query(PhotoRequest).filter(PhotoRequest.customer_id == uuid.UUID(target)).count() == requests_before
    assert db.query(PhotoRequestEmail).join(PhotoRequest).filter(PhotoRequest.customer_id == uuid.UUID(target)).count() == 0
    assert db.get(Customer, uuid.UUID(target)).stage == "interested"
    # (The test's own stage setup writes a pipeline audit; none may come from the photo email.)
    assert not [a for a in db.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(target)) if (a.meta or {}).get("source") == "photo_request_email"]

    monkeypatch.undo()
    r = client.post(f"/customers/{target}/photo-requests", json={"title": "x", "send_email": True}, headers=coord)
    assert r.status_code == 201 and r.json()["email"]["status"] == "queued"
    assert r.json()["pipeline"] == {"changed": True, "from": "interested", "stage": "photos_requested"}
    db.expire_all()
    assert db.get(Customer, uuid.UUID(target)).stage == "photos_requested"
    assert db.get(Customer, uuid.UUID(bystander)).stage == "interested"
    assert len([a for a in db.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(target)) if (a.meta or {}).get("source") == "photo_request_email"]) == 1
    # The patient's only open enquiry is linked to the request; the deal itself is unchanged.
    req = db.get(PhotoRequest, uuid.UUID(r.json()["request"]["id"]))
    assert str(req.deal_id) == deal["id"]
    assert db.get(Deal, uuid.UUID(deal["id"])).status.value == "open"


def test_assistant_sees_upload_status_and_proformas_but_not_photo_files_or_assessments(client, db, team):
    asst, doc = team["assistant"], team["doc_a"]
    issued = new_request(client, doc, team["pa"])
    rid = issued["request"]["id"]
    upload_and_submit(client, portal_session(client, issued["portal_url"]))
    photo_id = client.get(f"/photo-requests/{rid}", headers=doc).json()["photos"][0]["id"]
    client.post(f"/photo-requests/{rid}/assessments", json={"body": "ASSESSMENT-TEXT-123"}, headers=doc)
    client.post(f"/photo-requests/{rid}/notes", json={"body": "NOTE-TEXT-456"}, headers=doc)
    assert put_proforma(client, asst, team["pa"]).status_code == 201

    # Can see: upload status (patient list, request list, request summary) and the proforma.
    row = client.get("/care/patients", headers=asst).json()[0]
    assert row["latest_request"]["photos_uploaded"] is True and row["latest_request"]["photo_count"] == 1
    assert row["proforma"]["available"] is True
    queue = client.get("/photo-requests", headers=asst).json()
    assert [(q["id"], q["status"], q["photo_count"]) for q in queue] == [(rid, "uploaded", 1)]
    proforma = client.get(f"/customers/{team['pa']}/proforma", headers=asst).json()["current"]
    assert client.get(f"/customers/{team['pa']}/proforma/{proforma['id']}/content", headers=asst).status_code == 200

    # Cannot: photo files (view or download), photo metadata, assessments or notes.
    for path in (f"/photo-requests/{rid}/photos/{photo_id}/content", f"/photo-requests/{rid}/photos/{photo_id}/content?download=true"):
        assert client.get(path, headers=asst).status_code == 403, path
    responses = [
        client.get(f"/photo-requests/{rid}", headers=asst),
        client.get("/photo-requests", headers=asst),
        client.get("/care/patients", headers=asst),
        client.get(f"/care/patients/{team['pa']}", headers=asst),
    ]
    detail = responses[0].json()
    assert detail["photos"] is None and detail["assessments"] is None and detail["notes"] is None
    for r in responses:
        assert r.status_code == 200
        assert "ASSESSMENT-TEXT-123" not in r.text and "NOTE-TEXT-456" not in r.text and photo_id not in r.text
    assert client.post(f"/photo-requests/{rid}/photos/{photo_id}/hide", json={"reason": "x"}, headers=asst).status_code == 403
    # No audit record of the assistant viewing a photo was ever created.
    db.expire_all()
    assert not [a for a in db.query(AuditLog).filter(AuditLog.action.in_(["patient_photo.viewed", "patient_photo.downloaded"])) if str(a.actor_user_id) == uid(client, asst)]
