"""Patient photo requests: staff module, patient portal, storage and audit."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.db.models import (
    Appointment,
    AuditLog,
    Event,
    PatientPhoto,
    PhotoAccessLink,
    PhotoRequest,
    User,
)
from app.main import app
from app.services import photo_storage
from app.services.photo_portal_auth import failed_attempts

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 200
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 200


@pytest.fixture(autouse=True)
def _reset_limiter():
    failed_attempts.reset()
    yield
    failed_attempts.reset()


# --- helpers -------------------------------------------------------------------


def staff(client, db, role: str) -> dict:
    creds = {"email": f"{role}_{uuid.uuid4().hex[:8]}@example.com", "password": "ChangeMe123!"}
    r = client.post("/auth/register", json=creds)
    assert r.status_code == 201, r.text
    user = db.query(User).filter(User.email == creds["email"]).one()
    user.role = role
    db.commit()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_customer(client, headers, name="Ayse Patient") -> str:
    r = client.post("/customers", json={"name": name, "email": None, "phone": None, "company": None, "next_follow_up_at": None}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def new_request(client, headers, customer_id, **extra) -> dict:
    r = client.post(
        f"/customers/{customer_id}/photo-requests",
        json={"title": "Hair transplant assessment", "instructions": "Front, top and back of the head.", **extra},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def token_of(issued: dict) -> str:
    url = issued["portal_url"]
    assert "#token=" in url
    return url.split("#token=", 1)[1]


def portal(client, issued: dict) -> dict:
    r = client.post("/portal/photo-request/session", json={"token": token_of(issued)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def consent(client, ph) -> None:
    r = client.post("/portal/photo-request/consent", json={"version": settings.photo_consent_version, "accepted": True}, headers=ph)
    assert r.status_code == 204, r.text


def upload(client, ph, data=JPEG, filename="front.jpg", content_type="image/jpeg"):
    return client.put(
        "/portal/photo-request/photos",
        params={"filename": filename},
        content=data,
        headers={**ph, "Content-Type": content_type},
    )


def submitted_request(client, db, headers, customer_id, files=(JPEG,)) -> tuple[dict, dict, list[str]]:
    issued = new_request(client, headers, customer_id)
    ph = portal(client, issued)
    consent(client, ph)
    ids = []
    for data in files:
        r = upload(client, ph, data=data, filename="b.png", content_type="image/png") if data == PNG else upload(client, ph, data=data)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = client.post("/portal/photo-request/submit", headers=ph)
    assert r.status_code == 200, r.text
    return issued, ph, ids


def audit_actions(db, request_id) -> list[str]:
    db.expire_all()
    rows = db.query(AuditLog).filter(AuditLog.entity_type == "photo_request", AuditLog.entity_id == uuid.UUID(str(request_id))).all()
    return [r.action for r in rows]


def stored_files() -> set[str]:
    root = Path(settings.photo_storage_dir)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- 1. staff create ---------------------------------------------------------


def test_staff_creates_request_linked_to_appointment(client, db):
    coord = staff(client, db, "coordinator")
    cid = new_customer(client, coord)
    event = Event(owner_user_id=uuid.UUID(client.get("/auth/me", headers=coord).json()["id"]), name="London consult", starts_on=date.today(), ends_on=date.today())
    db.add(event)
    db.flush()
    start = datetime.now(tz=timezone.utc) + timedelta(days=3)
    appt = Appointment(event_id=event.id, customer_id=uuid.UUID(cid), starts_at=start, ends_at=start + timedelta(minutes=30))
    db.add(appt)
    db.commit()

    options = client.get(f"/customers/{cid}/photo-requests/link-options", headers=coord).json()
    assert [o["id"] for o in options["appointments"]] == [str(appt.id)]
    issued = new_request(client, coord, cid, appointment_id=str(appt.id))
    assert issued["request"]["status"] == "requested"
    assert issued["request"]["appointment_id"] == str(appt.id)
    assert issued["link"]["active"] is True

    # Only the hash of the token is stored.
    link = db.get(PhotoAccessLink, uuid.UUID(issued["link"]["id"]))
    assert link.token_hash != token_of(issued) and len(link.token_hash) == 64

    listed = client.get(f"/customers/{cid}/photo-requests", headers=coord).json()
    assert [r["id"] for r in listed] == [issued["request"]["id"]]

    # Appointment of another patient is rejected.
    other = new_customer(client, coord, "Someone Else")
    r = client.post(f"/customers/{other}/photo-requests", json={"title": "x", "appointment_id": str(appt.id)}, headers=coord)
    assert r.status_code == 422

    # Viewers cannot create requests; non-owners (owner isolation on) cannot see the patient.
    assert client.post(f"/customers/{cid}/photo-requests", json={"title": "x"}, headers=staff(client, db, "viewer")).status_code == 403
    # The default "user" role (what any new account gets) has no photo-module write access.
    assert client.post(f"/customers/{cid}/photo-requests", json={"title": "x"}, headers=staff(client, db, "user")).status_code == 403
    # Owner isolation: another coordinator cannot see this patient.
    assert client.post(f"/customers/{cid}/photo-requests", json={"title": "x"}, headers=staff(client, db, "coordinator")).status_code == 404

    actions = audit_actions(db, issued["request"]["id"])
    assert "photo_request.created" in actions and "photo_request.link_issued" in actions


# --- 2. patient happy path -------------------------------------------------------


def test_patient_uploads_and_submits_own_request(client, db):
    coord = staff(client, db, "coordinator")
    cid = new_customer(client, coord, "Ayse Yilmaz")
    issued = new_request(client, coord, cid)
    ph = portal(client, issued)

    r = client.get("/portal/photo-request", headers=ph)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Hair transplant assessment"
    assert body["patient_first_name"] == "Ayse"
    assert body["can_upload"] is True and body["consent"]["accepted"] is False
    assert settings.photo_reviewer_description in body["reviewer"]

    # Upload is refused until consent is recorded.
    assert upload(client, ph).status_code == 403
    consent(client, ph)

    for data, name, ctype in [(JPEG, "a.jpg", "image/jpeg"), (PNG, "b.png", "image/png"), (WEBP, "c.webp", "image/webp"), (HEIC, "d.heic", "image/heic")]:
        r = upload(client, ph, data=data, filename=name, content_type=ctype)
        assert r.status_code == 201, r.text

    # The patient can remove a photo before submitting.
    photos = client.get("/portal/photo-request", headers=ph).json()["photos"]
    assert len(photos) == 4
    assert client.delete(f"/portal/photo-request/photos/{photos[-1]['id']}", headers=ph).status_code == 204

    r = client.post("/portal/photo-request/submit", headers=ph)
    assert r.status_code == 200
    assert r.json()["status"] == "uploaded" and r.json()["can_upload"] is False
    # No more uploads after submission.
    assert upload(client, ph).status_code == 409

    detail = client.get(f"/photo-requests/{issued['request']['id']}", headers=coord).json()
    assert detail["request"]["status"] == "uploaded"
    assert detail["request"]["consent_status"] == "accepted"
    assert detail["request"]["consent_version"] == settings.photo_consent_version
    assert len([p for p in detail["photos"] if p["deleted_at"] is None]) == 3

    # Storage keys are random and never contain patient data or the original filename.
    for p in db.query(PatientPhoto).filter(PatientPhoto.request_id == uuid.UUID(issued["request"]["id"])):
        assert re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{32}\.(jpg|png|webp|heic)", p.storage_key), p.storage_key
        assert "ayse" not in p.storage_key.lower()


# --- 3. cross-patient isolation ---------------------------------------------------


def test_patient_cannot_reach_another_patients_request(client, db):
    coord = staff(client, db, "coordinator")
    a_issued, a_ph, _ = submitted_request(client, db, coord, new_customer(client, coord, "Patient A"))
    b_issued, b_ph, b_ids = submitted_request(client, db, coord, new_customer(client, coord, "Patient B"))

    # Patient A swaps in B's photo ID.
    assert client.get(f"/portal/photo-request/photos/{b_ids[0]}/content", headers=a_ph).status_code == 404
    assert client.delete(f"/portal/photo-request/photos/{b_ids[0]}", headers=a_ph).status_code == 404
    # B can fetch their own photo.
    r = client.get(f"/portal/photo-request/photos/{b_ids[0]}/content", headers=b_ph)
    assert r.status_code == 200 and r.content == JPEG

    # The portal session never works on staff routes, with or without IDs.
    assert client.get(f"/photo-requests/{b_issued['request']['id']}", headers=a_ph).status_code == 401
    assert client.get(f"/photo-requests/{b_issued['request']['id']}/photos/{b_ids[0]}/content", headers=a_ph).status_code == 401
    assert client.get("/customers", headers=a_ph).status_code == 401

    # Tampering with the session's request ID breaks the signature.
    token = a_ph["Authorization"].split(" ", 1)[1]
    head, payload, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = b_issued["request"]["id"]
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert client.get("/portal/photo-request", headers={"Authorization": f"Bearer {head}.{forged}.{sig}"}).status_code == 401

    # The portal only shows A's own request.
    assert client.get("/portal/photo-request", headers=a_ph).json()["title"] == a_issued["request"]["title"]


# --- 4. credential lifecycle ------------------------------------------------------


def test_expired_revoked_malformed_and_reused_links_are_rejected(client, db, monkeypatch):
    coord = staff(client, db, "coordinator")
    cid = new_customer(client, coord)

    # Malformed
    for bad in ["", "abc", "pr_short", "pr_" + "!" * 43, "x" * 150]:
        assert client.post("/portal/photo-request/session", json={"token": bad}).status_code == 401
    failed_attempts.reset()
    # Well-formed but unknown
    assert client.post("/portal/photo-request/session", json={"token": "pr_" + "A" * 43}).status_code == 401

    # Expired
    issued = new_request(client, coord, cid)
    link = db.get(PhotoAccessLink, uuid.UUID(issued["link"]["id"]))
    link.expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.post("/portal/photo-request/session", json={"token": token_of(issued)}).status_code == 401

    # Revoked: the link and any session opened from it both stop working.
    issued = client.post(f"/photo-requests/{issued['request']['id']}/links", headers=coord).json()
    ph = portal(client, issued)
    r = client.post(f"/photo-requests/{issued['request']['id']}/links/{issued['link']['id']}/revoke", json={"reason": "sent to wrong number"}, headers=coord)
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.post("/portal/photo-request/session", json={"token": token_of(issued)}).status_code == 401
    assert client.get("/portal/photo-request", headers=ph).status_code == 401

    # Reissuing replaces (revokes) the previous link.
    first = client.post(f"/photo-requests/{issued['request']['id']}/links", headers=coord).json()
    second = client.post(f"/photo-requests/{issued['request']['id']}/links", headers=coord).json()
    assert client.post("/portal/photo-request/session", json={"token": token_of(first)}).status_code == 401
    assert client.post("/portal/photo-request/session", json={"token": token_of(second)}).status_code == 200

    # Reuse beyond the allowed number of opens.
    monkeypatch.setattr(settings, "photo_link_max_uses", 2)
    limited = client.post(f"/photo-requests/{issued['request']['id']}/links", headers=coord).json()
    for _ in range(2):
        assert client.post("/portal/photo-request/session", json={"token": token_of(limited)}).status_code == 200
    assert client.post("/portal/photo-request/session", json={"token": token_of(limited)}).status_code == 401

    # A staff JWT is not a portal session, and a portal link token is not a session either.
    assert client.get("/portal/photo-request", headers=coord).status_code == 401
    assert client.get("/portal/photo-request", headers={"Authorization": f"Bearer {token_of(second)}"}).status_code == 401

    # Withdrawing the request kills its links.
    r = client.post(f"/photo-requests/{issued['request']['id']}/status", json={"status": "withdrawn"}, headers=coord)
    assert r.status_code == 200
    assert client.post("/portal/photo-request/session", json={"token": token_of(second)}).status_code == 401

    actions = audit_actions(db, issued["request"]["id"])
    assert "photo_request.link_revoked" in actions and "photo_portal.access_denied" in actions


def test_brute_force_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "photo_portal_max_failed_attempts", 3)
    for _ in range(3):
        assert client.post("/portal/photo-request/session", json={"token": "pr_" + uuid.uuid4().hex + "x" * 11}).status_code == 401
    assert client.post("/portal/photo-request/session", json={"token": "pr_" + "B" * 43}).status_code == 429


# --- 5. unauthenticated -----------------------------------------------------------


def test_unauthenticated_cannot_upload_view_or_download(client, db):
    coord = staff(client, db, "coordinator")
    issued, _, ids = submitted_request(client, db, coord, new_customer(client, coord))
    rid = issued["request"]["id"]
    assert client.put("/portal/photo-request/photos", params={"filename": "a.jpg"}, content=JPEG, headers={"Content-Type": "image/jpeg"}).status_code == 401
    assert client.get("/portal/photo-request").status_code == 401
    assert client.get(f"/portal/photo-request/photos/{ids[0]}/content").status_code == 401
    assert client.get(f"/photo-requests/{rid}/photos/{ids[0]}/content").status_code == 401
    assert client.get(f"/photo-requests/{rid}/photos/{ids[0]}/content?download=true").status_code == 401
    assert client.get(f"/photo-requests/{rid}").status_code == 401


# --- 6. validation ----------------------------------------------------------------


def test_invalid_spoofed_oversized_and_excess_files_are_rejected(client, db, monkeypatch):
    coord = staff(client, db, "coordinator")
    issued = new_request(client, coord, new_customer(client, coord))
    ph = portal(client, issued)
    consent(client, ph)
    before = stored_files()

    gif = b"GIF89a" + b"\x00" * 100
    # Unsupported format
    assert upload(client, ph, data=gif, filename="a.gif", content_type="image/gif").status_code == 415
    # Spoofed: PNG/GIF/text bytes behind a .jpg name and image/jpeg MIME
    assert upload(client, ph, data=PNG, filename="a.jpg", content_type="image/jpeg").status_code == 415
    assert upload(client, ph, data=gif, filename="a.jpg", content_type="image/jpeg").status_code == 415
    assert upload(client, ph, data=b"<script>alert(1)</script>" * 4, filename="a.jpg", content_type="image/jpeg").status_code == 415
    # Extension and MIME disagree
    assert upload(client, ph, data=JPEG, filename="a.jpg", content_type="image/png").status_code == 415
    assert upload(client, ph, data=JPEG, filename="a.png", content_type="image/jpeg").status_code == 415
    assert upload(client, ph, data=JPEG, filename="noext", content_type="image/jpeg").status_code == 415
    # Too small to be an image
    assert upload(client, ph, data=b"\xff\xd8\xff", filename="a.jpg").status_code == 415
    # Format disabled by configuration
    monkeypatch.setattr(settings, "photo_allowed_formats", ["jpeg"])
    assert upload(client, ph, data=PNG, filename="a.png", content_type="image/png").status_code == 415
    monkeypatch.setattr(settings, "photo_allowed_formats", ["jpeg", "png", "webp", "heic"])

    # Oversized (limit lowered to 1 MB; file is 1 MB + 1 byte)
    monkeypatch.setattr(settings, "photo_max_file_size_mb", 1)
    big = JPEG + b"\x00" * (1024 * 1024 + 1 - len(JPEG))
    assert upload(client, ph, data=big).status_code == 413

    # Too many photos
    monkeypatch.setattr(settings, "photo_max_files_per_request", 2)
    assert upload(client, ph).status_code == 201
    assert upload(client, ph).status_code == 201
    assert upload(client, ph).status_code == 409

    # Rejected uploads leave nothing behind in storage.
    added = stored_files() - before
    assert len(added) == 2 and not any(f.startswith(".incoming") for f in added)


# --- 7. streaming -----------------------------------------------------------------


def test_upload_is_streamed_in_chunks_not_buffered(client, db, monkeypatch):
    coord = staff(client, db, "coordinator")
    issued = new_request(client, coord, new_customer(client, coord))
    ph = portal(client, issued)
    consent(client, ph)

    # Reading the whole body into memory must never happen on this route.
    from starlette.requests import Request

    async def _no_body(self):  # pragma: no cover - fails the test if hit
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

    chunk = 64 * 1024
    n_chunks = 24  # 1.5 MB generated on the fly, never held as one buffer
    total = n_chunks * chunk

    async def body():
        yield JPEG[:16] + b"\x00" * (chunk - 16)
        for _ in range(n_chunks - 1):
            yield b"\x00" * chunk

    async def run(content_length: int, gen):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.put(
                "/portal/photo-request/photos",
                params={"filename": "big.jpg"},
                content=gen(),
                headers={**ph, "Content-Type": "image/jpeg", "Content-Length": str(content_length)},
            )

    r = asyncio.run(run(total, body))
    assert r.status_code == 201, r.text
    assert r.json()["size_bytes"] == total
    assert len(writes) >= n_chunks and max(writes) <= chunk

    # A body that grows past the limit mid-stream is cut off as soon as it crosses it,
    # even when the declared Content-Length was small.
    monkeypatch.setattr(settings, "photo_max_file_size_mb", 1)
    writes.clear()
    r = asyncio.run(run(1000, body))
    assert r.status_code == 413
    assert sum(writes) <= 1024 * 1024


# --- 8. no public access to files -------------------------------------------------


def test_private_files_have_no_public_path(client, db, monkeypatch):
    coord = staff(client, db, "coordinator")
    issued, _, ids = submitted_request(client, db, coord, new_customer(client, coord))
    photo = db.get(PatientPhoto, uuid.UUID(ids[0]))
    key = photo.storage_key

    # No static mounts exist and guessed paths do not resolve.
    from starlette.routing import Mount

    assert not [r for r in app.routes if isinstance(r, Mount)]
    for path in [f"/{key}", f"/static/{key}", f"/photos/{key}", f"/patient_photos/{key}", f"/data/patient_photos/{key}", f"/media/{key}"]:
        assert client.get(path).status_code in (404, 405)

    # Storage is a private directory with owner-only permissions.
    path = Path(settings.photo_storage_dir) / key
    assert path.exists() and (path.stat().st_mode & 0o077) == 0
    assert not str(Path(settings.photo_storage_dir).resolve()).startswith(str(Path("frontend/public").resolve()))

    # Authorised staff get a no-store stream; roles without photo access get 403.
    r = client.get(f"/photo-requests/{issued['request']['id']}/photos/{ids[0]}/content", headers=coord)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["cache-control"].startswith("no-store")
    assert r.headers["x-content-type-options"] == "nosniff"
    viewer = staff(client, db, "viewer")
    assert client.get(f"/photo-requests/{issued['request']['id']}/photos/{ids[0]}/content", headers=viewer).status_code == 403
    # Owner isolation: another coordinator cannot see this patient's photos at all.
    assert client.get(f"/photo-requests/{issued['request']['id']}/photos/{ids[0]}/content", headers=staff(client, db, "coordinator")).status_code == 404
    # The default "user" role never gets photos, even with sharing on.
    monkeypatch.setattr(settings, "share_customers_across_users", True)
    plain = staff(client, db, "user")
    assert client.get(f"/photo-requests/{issued['request']['id']}/photos/{ids[0]}/content", headers=plain).status_code == 403
    d = client.get(f"/photo-requests/{issued['request']['id']}", headers=plain).json()
    assert d["photos"] is None and d["notes"] is None and d["assessments"] is None
    monkeypatch.setattr(settings, "share_customers_across_users", False)
    # The viewer sees status only, not photos/notes/assessments.
    monkeypatch.setattr(settings, "share_customers_across_users", True)
    assert client.get(f"/photo-requests/{issued['request']['id']}/photos/{ids[0]}/content", headers=viewer).status_code == 403
    d = client.get(f"/photo-requests/{issued['request']['id']}", headers=viewer).json()
    assert d["photos"] is None and d["notes"] is None and d["assessments"] is None


# --- 9 + 10 + 11. roles, notes vs assessments, audit --------------------------------


def test_role_permissions_for_notes_assessments_and_status(client, db, monkeypatch):
    coord = staff(client, db, "coordinator")
    assistant = staff(client, db, "user")  # default role: no notes or assessments
    doctor = staff(client, db, "doctor")
    manager = staff(client, db, "manager")
    admin = staff(client, db, "admin")
    cid = new_customer(client, coord, "Mehmet Patient")
    issued, ph, ids = submitted_request(client, db, coord, cid, files=(JPEG, PNG))
    rid = issued["request"]["id"]

    # The doctor reviews across owners even with owner isolation on.
    assert client.get(f"/photo-requests/{rid}", headers=doctor).status_code == 200
    queue = client.get("/photo-requests", params={"status": "uploaded"}, headers=doctor).json()
    assert rid in [q["id"] for q in queue]

    # Viewing and downloading are audited.
    assert client.get(f"/photo-requests/{rid}/photos/{ids[0]}/content", headers=doctor).status_code == 200
    assert client.get(f"/photo-requests/{rid}/photos/{ids[1]}/content?download=true", headers=doctor).status_code == 200

    # Coordinator: internal notes and admin status, never clinical actions.
    assert client.post(f"/photo-requests/{rid}/status", json={"status": "in_review"}, headers=coord).status_code == 200
    r = client.post(f"/photo-requests/{rid}/notes", json={"body": "INTERNAL-NOTE-XYZ patient prefers mornings"}, headers=coord)
    assert r.status_code == 201
    note_id = r.json()["notes"][0]["id"]
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "nope"}, headers=coord).status_code == 403
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "nope"}, headers=assistant).status_code == 403
    assert client.post(f"/photo-requests/{rid}/notes", json={"body": "nope"}, headers=assistant).status_code == 403
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "nope"}, headers=admin).status_code == 403
    assert client.post(f"/photo-requests/{rid}/assessments", json={"body": "nope"}, headers=manager).status_code == 403
    for target in ("reviewed", "more_photos_needed"):
        assert client.post(f"/photo-requests/{rid}/status", json={"status": target, "patient_message": "x"}, headers=coord).status_code == 403

    # Reviewed requires an assessment first.
    assert client.post(f"/photo-requests/{rid}/status", json={"status": "reviewed"}, headers=doctor).status_code == 409

    # Doctor: create and update an assessment; history is kept.
    r = client.post(f"/photo-requests/{rid}/assessments", json={"body": "CLINICAL-ASSESS-ABC Norwood 3"}, headers=doctor)
    assert r.status_code == 201
    a = r.json()["assessments"][0]
    assert a["author_role"] == "doctor"
    r = client.patch(f"/photo-requests/{rid}/assessments/{a['id']}", json={"body": "CLINICAL-ASSESS-ABC Norwood 4"}, headers=doctor)
    assert r.status_code == 200
    a = r.json()["assessments"][0]
    assert a["version"] == 2 and [rev["body"] for rev in a["revisions"]] == ["CLINICAL-ASSESS-ABC Norwood 3", "CLINICAL-ASSESS-ABC Norwood 4"]
    # Notes and assessments stay separate.
    assert all("CLINICAL" not in n["body"] for n in r.json()["notes"])

    # Nobody else can edit the doctor's assessment; the doctor cannot edit the coordinator's note.
    assert client.patch(f"/photo-requests/{rid}/assessments/{a['id']}", json={"body": "changed"}, headers=coord).status_code == 403
    assert client.patch(f"/photo-requests/{rid}/assessments/{a['id']}", json={"body": "changed"}, headers=admin).status_code == 403
    assert client.patch(f"/photo-requests/{rid}/notes/{note_id}", json={"body": "changed"}, headers=doctor).status_code == 403
    r = client.patch(f"/photo-requests/{rid}/notes/{note_id}", json={"body": "INTERNAL-NOTE-XYZ prefers afternoons"}, headers=coord)
    assert r.status_code == 200 and r.json()["notes"][0]["version"] == 2

    # Doctor asks for more photos; the patient sees only the patient message.
    r = client.post(
        f"/photo-requests/{rid}/status",
        json={"status": "more_photos_needed", "patient_message": "Please add a photo of the crown.", "reason": "INTERNAL-REASON-QQQ"},
        headers=doctor,
    )
    assert r.status_code == 200 and r.json()["request"]["upload_round"] == 2
    portal_view = client.get("/portal/photo-request", headers=ph)
    assert portal_view.status_code == 200
    text = portal_view.text
    assert "Please add a photo of the crown." in text
    for secret in ("INTERNAL-NOTE-XYZ", "CLINICAL-ASSESS-ABC", "INTERNAL-REASON-QQQ", "Norwood", "\"author_", "\"notes\"", "\"assessments\"", "coordinator", "@example.com"):
        assert secret not in text
    assert portal_view.json()["photos"] == []  # fresh round
    assert upload(client, ph, data=PNG, filename="crown.png", content_type="image/png").status_code == 201
    r = client.post("/portal/photo-request/submit", headers=ph)
    assert r.status_code == 200
    for secret in ("INTERNAL-NOTE-XYZ", "CLINICAL-ASSESS-ABC", "INTERNAL-REASON-QQQ"):
        assert secret not in r.text

    assert client.post(f"/photo-requests/{rid}/status", json={"status": "reviewed"}, headers=doctor).status_code == 200
    # Invalid transition
    assert client.post(f"/photo-requests/{rid}/status", json={"status": "withdrawn"}, headers=coord).status_code == 409
    assert client.post(f"/photo-requests/{rid}/status", json={"status": "closed", "reason": "treatment booked"}, headers=coord).status_code == 200

    # Photo hiding is manager/admin only and is a soft delete.
    assert client.post(f"/photo-requests/{rid}/photos/{ids[0]}/hide", json={"reason": "duplicate"}, headers=coord).status_code == 403
    r = client.post(f"/photo-requests/{rid}/photos/{ids[0]}/hide", json={"reason": "duplicate"}, headers=manager)
    assert r.status_code == 404  # owner isolation: manager doesn't own this patient
    monkeypatch.setattr(settings, "share_customers_across_users", True)  # production setting
    r = client.post(f"/photo-requests/{rid}/photos/{ids[0]}/hide", json={"reason": "duplicate"}, headers=manager)
    assert r.status_code == 200 and r.json()["deleted_at"] is not None
    monkeypatch.setattr(settings, "share_customers_across_users", False)
    db.expire_all()
    assert db.get(PatientPhoto, uuid.UUID(ids[0])) is not None  # metadata kept

    detail = client.get(f"/photo-requests/{rid}", headers=coord).json()
    assert [h["to_status"] for h in detail["history"]] == [
        "requested", "uploaded", "in_review", "more_photos_needed", "uploaded", "reviewed", "closed",
    ]
    assert {h["actor_type"] for h in detail["history"]} == {"staff", "patient"}

    actions = audit_actions(db, rid)
    for expected in [
        "photo_request.created",
        "photo_request.link_issued",
        "photo_portal.session_opened",
        "photo_request.consent_recorded",
        "patient_photo.uploaded",
        "photo_request.status_changed",
        "patient_photo.viewed",
        "patient_photo.downloaded",
        "photo_request.note_created",
        "photo_request.note_updated",
        "photo_request.assessment_created",
        "photo_request.assessment_updated",
        "patient_photo.hidden",
    ]:
        assert expected in actions, expected
    assert actions.count("photo_request.status_changed") == 6
    assert actions.count("patient_photo.uploaded") == 3

    # Audit rows carry no clinical or note text.
    db.expire_all()
    for row in db.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(rid)):
        dumped = json.dumps([row.before, row.after, row.meta])
        assert "Norwood" not in dumped and "INTERNAL-NOTE" not in dumped


def test_customer_with_photo_requests_cannot_be_hard_deleted(client, db):
    coord = staff(client, db, "coordinator")
    cid = new_customer(client, coord)
    new_request(client, coord, cid)
    r = client.delete(f"/customers/{cid}", headers=coord)
    assert r.status_code == 409
    assert client.get(f"/customers/{cid}", headers=coord).status_code == 200
