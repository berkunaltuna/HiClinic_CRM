from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Appointment, AutomationSend, Deal, Event, EventDay, OutboundMessage
from app.services import messaging_automations as ma


DAY = date.today() + timedelta(days=45)
UK_TZ_NAME = datetime(DAY.year, DAY.month, DAY.day, 10, tzinfo=ZoneInfo("Europe/London")).tzname()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _template(client, admin_headers, channel: str, body: str, subject: str | None = None, provider_template_id: str | None = None,
              approved: bool = True) -> str:
    payload = {"channel": channel, "name": f"t_{uuid.uuid4().hex[:8]}", "body": body, "subject": subject}
    if provider_template_id:
        payload["provider_template_id"] = provider_template_id
        payload["provider_approved"] = approved
    r = client.post("/templates", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _automations_off(client, admin_headers):
    # Settings rows live for the whole test session; start every test with both paused.
    for key in ma.AUTOMATION_KEYS:
        r = client.patch(f"/automations/{key}", json={"is_enabled": False, "require_approval": False, "max_per_run": None}, headers=admin_headers)
        assert r.status_code == 200, r.text


@pytest.fixture()
def templates(client, admin_headers) -> dict[str, str]:
    return {
        "email": _template(
            client, admin_headers, "email",
            "<p>Hi {{first_name}}, see you on {{appointment_date}} at {{appointment_time}}-{{appointment_end_time}} "
            "({{appointment_timezone}}), {{appointment_location}}. Questions: {{clinic_phone}}</p>",
            subject="Your Health Clinic appointment is confirmed",
        ),
        "whatsapp": _template(
            client, admin_headers, "whatsapp",
            "Hi {{first_name}}, confirmed: {{appointment_date}} {{appointment_time}} ({{appointment_timezone}}), "
            "{{appointment_location}}. Call {{clinic_phone}}",
            provider_template_id="HX_confirm",
        ),
        "update_email": _template(
            client, admin_headers, "email",
            "<p>Hi {{first_name}}, your appointment moved to {{appointment_date}} {{appointment_time}} "
            "({{appointment_timezone}}), {{appointment_location}}. {{clinic_phone}}</p>",
            subject="Your Health Clinic appointment has changed",
        ),
        "followup_email": _template(
            client, admin_headers, "email",
            "<p>Hi {{first_name}}, thanks for your enquiry. Call {{clinic_phone}}.</p>",
            subject="Following up on your Health Clinic enquiry",
        ),
        "followup_whatsapp": _template(
            client, admin_headers, "whatsapp",
            "Hi {{first_name}}, can we help you book? {{clinic_phone}}",
            provider_template_id="HX_followup",
        ),
    }


def _set_clinic(client, admin_headers, phone: str | None = "+44 20 7946 0000"):
    r = client.put("/automations/clinic", json={"clinic_name": "Health Clinic", "contact_phone": phone, "contact_email": "hello@example.com"}, headers=admin_headers)
    assert r.status_code == 200, r.text


def _configure(client, admin_headers, key: str, **fields):
    """Switch off then on, so active_since is stamped fresh for this test."""
    r = client.patch(f"/automations/{key}", json={"is_enabled": False}, headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.patch(f"/automations/{key}", json={"is_enabled": True, **fields}, headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _enable_confirmation(client, admin_headers, templates, **overrides):
    _set_clinic(client, admin_headers)
    fields = dict(
        email_enabled=True,
        whatsapp_enabled=True,
        email_template_id=templates["email"],
        whatsapp_template_id=templates["whatsapp"],
        update_email_template_id=templates["update_email"],
        update_whatsapp_template_id=templates["whatsapp"],
        send_updates=True,
    )
    fields.update(overrides)
    return _configure(client, admin_headers, "appointment_confirmation", **fields)


def _enable_followup(client, admin_headers, templates, **overrides):
    _set_clinic(client, admin_headers)
    fields = dict(
        email_enabled=True,
        whatsapp_enabled=False,
        email_template_id=templates["followup_email"],
        whatsapp_template_id=templates["followup_whatsapp"],
        delay_minutes=24 * 60,
    )
    fields.update(overrides)
    return _configure(client, admin_headers, "lead_followup", **fields)


def _customer(client, auth_headers, *, email="pat@example.com", phone="+44 7700 900123", **extra) -> str:
    r = client.post("/customers", json={"name": "Pat Jones", "email": email, "phone": phone}, headers=auth_headers)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    if extra:
        r = client.patch(f"/customers/{cid}", json=extra, headers=auth_headers)
        assert r.status_code == 200, r.text
    return cid


def _event(client, auth_headers, location: str | None = "Health Clinic, 1 Harley Street, London") -> str:
    r = client.post(
        "/events",
        json={
            "name": "London consultation days",
            "location": location,
            "starts_on": str(DAY),
            "ends_on": str(DAY),
            "days": [{"day": str(DAY), "start_time": "09:00", "end_time": "17:00", "slot_minutes": 30}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _book(client, auth_headers, event_id: str, customer_id: str, start: str = "10:00", end: str = "10:30") -> str:
    r = client.post(
        f"/events/{event_id}/appointments",
        json={"customer_id": customer_id, "starts_at": f"{DAY}T{start}:00", "ends_at": f"{DAY}T{end}:00"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sends(db, customer_id, key: str | None = None) -> list[AutomationSend]:
    db.expire_all()
    q = db.query(AutomationSend).filter(AutomationSend.customer_id == uuid.UUID(customer_id))
    if key:
        q = q.filter(AutomationSend.automation_key == key)
    return q.order_by(AutomationSend.revision, AutomationSend.created_at, AutomationSend.channel).all()


def _outbound(db, customer_id) -> list[OutboundMessage]:
    db.expire_all()
    return db.query(OutboundMessage).filter(OutboundMessage.customer_id == uuid.UUID(customer_id)).all()


def _worker_result(db, send: AutomationSend, status: str, error: str | None = None):
    msg = db.get(OutboundMessage, send.outbound_message_id)
    msg.status = status
    msg.last_error = error
    db.commit()


# ---------------------------------------------------------------------------
# Contact validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+44 7700 900123", "+447700900123"),
        ("0044 7700 900123", "+447700900123"),
        ("07700 900123", "+447700900123"),
        ("whatsapp:+905321234567", "+905321234567"),
        ("7700900123", None),  # no prefix: country code is ambiguous
        ("+44 12", None),
        ("", None),
        (None, None),
    ],
)
def test_whatsapp_number_normalisation(raw, expected):
    assert ma.normalise_whatsapp_number(raw) == expected


# ---------------------------------------------------------------------------
# Automation 1: appointment confirmation
# ---------------------------------------------------------------------------


def test_confirmation_uses_event_slot_and_only_permitted_channels(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    # No phone on file: WhatsApp can't be used, email still goes.
    cid = _customer(client, auth_headers, phone=None)
    appt_id = _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    by_channel = {s.channel: s for s in sends}
    assert set(by_channel) == {"email", "whatsapp"}
    assert by_channel["whatsapp"].status == "skipped"
    assert "No valid WhatsApp number" in by_channel["whatsapp"].reason

    email = by_channel["email"]
    assert email.status == "queued" and email.kind == "confirmation" and email.attempted_at is not None
    assert email.appointment_id == uuid.UUID(appt_id)
    body = email.rendered_body
    assert f"{DAY:%A} {DAY.day} {DAY:%B %Y}" in body
    assert "10:00-10:30" in body
    assert f"UK time, {UK_TZ_NAME}" in body
    assert "1 Harley Street" in body and "+44 20 7946 0000" in body
    assert email.rendered_subject == "Your Health Clinic appointment is confirmed"

    msgs = _outbound(db, cid)
    assert len(msgs) == 1 and msgs[0].channel == "email" and msgs[0].status == "queued"
    assert msgs[0].variables["appointment_time"] == "10:00"

    # Worker delivers it -> outcome copied back and recorded on the deal.
    _worker_result(db, email, "sent")
    ma.run_tick(db)
    db.expire_all()
    email = db.get(AutomationSend, email.id)
    assert email.status == "sent" and email.sent_at is not None
    deal = db.get(Deal, db.get(Appointment, uuid.UUID(appt_id)).deal_id)
    assert deal.confirmation_channel == "auto_email" and deal.confirmation_sent_at is not None


def test_whatsapp_confirmation_uses_approved_template_variables(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, email_enabled=False)
    cid = _customer(client, auth_headers, phone="07700 900456")
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.channel == "whatsapp" and send.status == "queued"
    [msg] = _outbound(db, cid)
    # Twilio Content variables are positional, in the order the fields appear in the template.
    assert msg.variables["1"] == "Pat"
    assert msg.variables["3"] == "10:00"
    assert msg.variables["4"] == f"UK time, {UK_TZ_NAME}"
    assert msg.template_id == uuid.UUID(templates["whatsapp"])


def test_whatsapp_without_approved_template_is_held_for_review(client, db, auth_headers, admin_headers, templates):
    free_form = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}, {{appointment_date}} {{appointment_time}}")
    _enable_confirmation(client, admin_headers, templates, email_enabled=False, whatsapp_template_id=free_form)
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "needs_review" and "Content SID" in send.reason
    assert _outbound(db, cid) == []


def test_invalid_contact_details_skip_channel(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers, email=None, phone="7700900123")
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    reasons = {s.channel: (s.status, s.reason) for s in _sends(db, cid, ma.CONFIRMATION)}
    assert reasons["email"] == ("skipped", "No valid email address on file")
    assert reasons["whatsapp"][0] == "skipped" and "No valid WhatsApp number" in reasons["whatsapp"][1]
    assert _outbound(db, cid) == []


def test_opted_out_patient_gets_no_confirmation(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers, can_contact=False)
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    assert sends and all(s.status == "skipped" and s.reason == "Patient has opted out of contact" for s in sends)
    assert _outbound(db, cid) == []


def test_same_booking_processed_twice_sends_once(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    appt_id = _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)
    ma.run_tick(db)
    auto = ma.get_automation(db, ma.CONFIRMATION)
    clinic = ma.get_clinic_settings(db)
    appt = db.get(Appointment, uuid.UUID(appt_id))
    assert ma.process_appointment(db, auto, clinic, appt, _now()) == []
    db.commit()

    assert len(_sends(db, cid, ma.CONFIRMATION)) == 1
    assert len(_outbound(db, cid)) == 1


def test_booking_with_missing_location_is_flagged_then_sent_once_fixed(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=None)
    _book(client, auth_headers, event_id, cid)

    ma.run_tick(db)
    [review] = _sends(db, cid, ma.CONFIRMATION)
    assert review.channel is None and review.status == "needs_review"
    assert "no location or online-call details" in review.reason
    assert _outbound(db, cid) == []

    r = client.get("/automations/sends", params={"attention": True}, headers=auth_headers)
    assert review.id in {uuid.UUID(s["id"]) for s in r.json()}

    r = client.patch(f"/events/{event_id}", json={"location": "Zoom: https://zoom.example/j/123"}, headers=auth_headers)
    assert r.status_code == 200
    ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    assert {(s.channel, s.status) for s in sends} == {(None, "resolved"), ("email", "queued")}
    assert "zoom.example" in next(s for s in sends if s.channel == "email").rendered_body
    assert len(_outbound(db, cid)) == 1


def test_booking_not_on_timetable_slot_is_flagged(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers)
    # Bypass the API's slot validation, e.g. legacy data: 10:10 is not a 30-minute grid slot.
    db.add(Appointment(event_id=uuid.UUID(event_id), customer_id=uuid.UUID(cid),
                       starts_at=datetime(DAY.year, DAY.month, DAY.day, 10, 10, tzinfo=timezone.utc),
                       ends_at=datetime(DAY.year, DAY.month, DAY.day, 10, 40, tzinfo=timezone.utc), status="booked"))
    db.commit()

    ma.run_tick(db)

    [review] = _sends(db, cid, ma.CONFIRMATION)
    assert review.status == "needs_review" and "does not match a slot" in review.reason
    assert _outbound(db, cid) == []


def test_slot_in_uk_clock_change_hour_is_ambiguous(db):
    change_day = date(2026, 10, 25)  # UK clocks go back at 02:00 BST -> 01:00 GMT
    event = Event(owner_user_id=uuid.uuid4(), name="Late October", location="London", starts_on=change_day, ends_on=change_day, is_active=True, slot_capacity=1)
    event.days = [EventDay(day=change_day, start_time=datetime(2000, 1, 1, 0).time(), end_time=datetime(2000, 1, 1, 3).time(), slot_minutes=30)]
    appt = Appointment(starts_at=datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc), ends_at=datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc), status="booked")
    appt.event = event
    slot, problem = ma.resolve_slot(db, appt)
    db.rollback()
    assert slot is None and "clocks change" in problem


def test_reschedule_sends_one_updated_confirmation(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers)
    appt_id = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    [first] = _sends(db, cid, ma.CONFIRMATION)
    _worker_result(db, first, "sent")
    ma.run_tick(db)

    r = client.patch(f"/events/{event_id}/appointments/{appt_id}",
                     json={"starts_at": f"{DAY}T14:00:00", "ends_at": f"{DAY}T14:30:00"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    ma.run_tick(db)
    ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    assert [(s.revision, s.kind, s.status) for s in sends] == [(1, "confirmation", "sent"), (2, "update", "queued")]
    update = sends[1]
    assert "moved to" in update.rendered_body and "14:00" in update.rendered_body
    assert update.rendered_subject == "Your Health Clinic appointment has changed"
    assert len(_outbound(db, cid)) == 2

    _worker_result(db, update, "sent")
    ma.run_tick(db)
    db.expire_all()
    deal = db.get(Deal, db.get(Appointment, uuid.UUID(appt_id)).deal_id)
    assert deal.confirmation_sent_at is not None
    r = client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers)
    assert "appointment.update_sent" in {a["action"] for a in r.json()}


def test_reschedule_with_updates_switched_off_is_recorded_not_sent(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, send_updates=False)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers)
    appt_id = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    _worker_result(db, _sends(db, cid, ma.CONFIRMATION)[0], "sent")
    ma.run_tick(db)

    client.patch(f"/events/{event_id}/appointments/{appt_id}", json={"starts_at": f"{DAY}T15:00:00", "ends_at": f"{DAY}T15:30:00"}, headers=auth_headers)
    ma.run_tick(db)

    latest = _sends(db, cid, ma.CONFIRMATION)[-1]
    assert latest.revision == 2 and latest.status == "skipped" and "switched off" in latest.reason
    assert len(_outbound(db, cid)) == 1


def test_queued_confirmation_is_cancelled_if_booking_cancelled_before_sending(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers)
    appt_id = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)

    client.patch(f"/events/{event_id}/appointments/{appt_id}", json={"status": "cancelled"}, headers=auth_headers)
    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "cancelled" and "cancelled" in send.reason
    [msg] = _outbound(db, cid)
    assert msg.status == "cancelled"


def test_bookings_made_before_enabling_are_not_backfilled(client, db, auth_headers, admin_headers, templates):
    client.patch("/automations/appointment_confirmation", json={"is_enabled": False}, headers=admin_headers)
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers), cid)
    _enable_confirmation(client, admin_headers, templates)

    ma.run_tick(db)

    assert _sends(db, cid) == []


def test_provider_failure_is_logged_visible_and_not_retried(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers), cid)
    ma.run_tick(db)
    [send] = _sends(db, cid, ma.CONFIRMATION)

    _worker_result(db, send, "failed", "SMTP 550 mailbox unavailable")
    ma.run_tick(db)
    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "failed" and send.reason == "SMTP 550 mailbox unavailable"
    assert len(_outbound(db, cid)) == 1  # no automatic resend

    r = client.get("/automations/sends", params={"attention": True}, headers=auth_headers)
    row = next(s for s in r.json() if s["id"] == str(send.id))
    assert row["channel"] == "email" and row["reason"] == "SMTP 550 mailbox unavailable" and row["attempted_at"]

    r = client.post(f"/automations/sends/{send.id}/dismiss", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    ma.run_tick(db)
    assert len(_outbound(db, cid)) == 1


# ---------------------------------------------------------------------------
# Automation 2: lead follow-up
# ---------------------------------------------------------------------------


def test_followup_sent_only_after_delay_and_only_once(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, delay_minutes=24 * 60)
    cid = _customer(client, auth_headers)

    ma.run_tick(db, now=_now() + timedelta(hours=23))
    assert _sends(db, cid, ma.FOLLOWUP) == []

    later = _now() + timedelta(hours=25)
    ma.run_tick(db, now=later)
    ma.run_tick(db, now=later + timedelta(minutes=5))

    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.channel == "email" and send.status == "queued" and send.kind == "followup"
    assert send.rendered_subject == "Following up on your Health Clinic enquiry"
    assert len(_outbound(db, cid)) == 1


def test_followup_delay_is_configurable(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, delay_minutes=2 * 60)
    cid = _customer(client, auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=3))
    assert [s.status for s in _sends(db, cid, ma.FOLLOWUP)] == ["queued"]


def test_followup_skipped_when_lead_books_during_delay(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "skipped"
    assert send.reason in ("Lead has an appointment", "Lead is no longer new (stage: appointment_booked)")
    assert _outbound(db, cid) == []


@pytest.mark.parametrize("contact", ["call", "email_logged", "staff_message_sent"])
def test_followup_skipped_when_staff_contacted_during_delay(client, db, auth_headers, admin_headers, templates, contact):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    if contact == "call":
        r = client.post(f"/customers/{cid}/interactions", json={"channel": "call", "direction": "outbound", "content": "Left voicemail"}, headers=auth_headers)
    elif contact == "email_logged":
        r = client.post(f"/customers/{cid}/email/send", json={"subject": "Hello", "body": "Hi there"}, headers=auth_headers)
    else:
        r = client.post(f"/inbox/customers/{cid}/send-text", json={"channel": "whatsapp", "body": "Hi from the clinic"}, headers=auth_headers)
        db.query(OutboundMessage).filter(OutboundMessage.id == uuid.UUID(r.json()["id"])).update({OutboundMessage.status: "sent"})
        db.commit()
    assert r.status_code in (201, 204), r.text
    before = len(_outbound(db, cid))

    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "skipped" and send.channel is None
    assert len(_outbound(db, cid)) == before


def test_followup_respects_opt_out_and_contact_details(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, whatsapp_enabled=True)
    opted_out = _customer(client, auth_headers, can_contact=False)
    email_only = _customer(client, auth_headers, phone=None)

    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [s] = _sends(db, opted_out, ma.FOLLOWUP)
    assert s.status == "skipped" and s.reason == "Lead has opted out of contact"
    statuses = {s.channel: (s.status, s.reason) for s in _sends(db, email_only, ma.FOLLOWUP)}
    assert statuses["email"][0] == "queued"
    assert statuses["whatsapp"][0] == "skipped" and "No valid WhatsApp number" in statuses["whatsapp"][1]
    assert [m.channel for m in _outbound(db, email_only)] == ["email"]


def test_queued_followup_cancelled_if_staff_contacts_before_worker_sends(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    later = _now() + timedelta(hours=25)
    ma.run_tick(db, now=later)
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "queued"

    client.post(f"/customers/{cid}/interactions", json={"channel": "call", "direction": "outbound", "content": "Spoke to patient"}, headers=auth_headers)
    ma.run_tick(db, now=later + timedelta(minutes=1))

    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "cancelled" and "already been contacted" in send.reason
    assert _outbound(db, cid)[0].status == "cancelled"


def test_followup_not_cancelled_by_its_own_queued_message(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    later = _now() + timedelta(hours=25)
    ma.run_tick(db, now=later)
    ma.run_tick(db, now=later + timedelta(minutes=1))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "queued"


def test_leads_created_before_enabling_are_not_followed_up(client, db, auth_headers, admin_headers, templates):
    client.patch("/automations/lead_followup", json={"is_enabled": False}, headers=admin_headers)
    cid = _customer(client, auth_headers)
    _enable_followup(client, admin_headers, templates)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    assert _sends(db, cid) == []


def test_paused_automation_sends_nothing(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    client.patch("/automations/lead_followup", json={"is_enabled": False}, headers=admin_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    assert _sends(db, cid) == []


def test_missing_clinic_contact_holds_send_for_review(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    _set_clinic(client, admin_headers, phone=None)
    cid = _customer(client, auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "needs_review" and "clinic_phone" in send.reason
    assert _outbound(db, cid) == []


# ---------------------------------------------------------------------------
# Admin controls
# ---------------------------------------------------------------------------


def test_admin_controls_and_validation(client, auth_headers, admin_headers, templates):
    r = client.patch("/automations/lead_followup", json={"is_enabled": True}, headers=auth_headers)
    assert r.status_code == 403
    r = client.put("/automations/clinic", json={"contact_phone": "123"}, headers=auth_headers)
    assert r.status_code == 403

    r = client.patch("/automations/lead_followup", json={"delay_minutes": 5}, headers=admin_headers)
    assert r.status_code == 400
    r = client.patch("/automations/lead_followup", json={"email_template_id": templates["followup_whatsapp"]}, headers=admin_headers)
    assert r.status_code == 400

    overview = _enable_followup(client, admin_headers, templates, delay_minutes=48 * 60)
    follow = next(a for a in overview["automations"] if a["key"] == "lead_followup")
    assert follow["is_enabled"] and follow["delay_minutes"] == 48 * 60 and follow["active_since"]
    assert "appointment_date" not in follow["supported_fields"]

    r = client.get("/automations", headers=auth_headers)
    assert r.status_code == 200
    assert {a["key"] for a in r.json()["automations"]} == {"appointment_confirmation", "lead_followup"}


def test_opt_out_change_is_stamped_with_note(client, auth_headers):
    cid = _customer(client, auth_headers, can_contact=False, consent_source="Replied STOP 14 Oct")
    r = client.get(f"/customers/{cid}", headers=auth_headers)
    body = r.json()
    assert body["can_contact"] is False and body["consent_updated_at"]
    assert body["consent_source"] == "Replied STOP 14 Oct"
    assert "whatsapp_consent" not in body


def test_template_update_sets_and_clears_twilio_content_sid(client, admin_headers):
    tid = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}")
    r = client.patch(f"/templates/{tid}", json={"provider_template_id": " HX123 "}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["provider_template_id"] == "HX123"
    r = client.patch(f"/templates/{tid}", json={"body": "Hello {{first_name}}"}, headers=admin_headers)
    assert r.json()["provider_template_id"] == "HX123"
    r = client.patch(f"/templates/{tid}", json={"provider_template_id": ""}, headers=admin_headers)
    assert r.json()["provider_template_id"] is None


def test_max_per_run_limits_patients_messaged_per_check(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, max_per_run=2)
    # A lead with no email address is decided (skipped) but must not use up the limit.
    no_consent = _customer(client, auth_headers, email=None)
    leads = [_customer(client, auth_headers) for _ in range(5)]
    later = _now() + timedelta(hours=25)

    def queued():
        return sum(1 for c in leads for s in _sends(db, c, ma.FOLLOWUP) if s.status == "queued")

    ma.run_tick(db, now=later)
    assert queued() == 2
    assert _sends(db, no_consent, ma.FOLLOWUP)[0].status == "skipped"
    ma.run_tick(db, now=later + timedelta(minutes=1))
    assert queued() == 4
    ma.run_tick(db, now=later + timedelta(minutes=2))
    ma.run_tick(db, now=later + timedelta(minutes=3))
    assert queued() == 5
    assert all(len(_outbound(db, c)) == 1 for c in leads)


def test_max_per_run_applies_to_confirmations_and_can_be_cleared(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, max_per_run=1)
    event_id = _event(client, auth_headers)
    patients = [_customer(client, auth_headers) for _ in range(3)]
    for i, cid in enumerate(patients):
        _book(client, auth_headers, event_id, cid, start=f"1{i}:00", end=f"1{i}:30")

    ma.run_tick(db)
    assert sum(len(_sends(db, c, ma.CONFIRMATION)) for c in patients) == 1

    r = client.patch("/automations/appointment_confirmation", json={"max_per_run": None}, headers=admin_headers)
    assert r.status_code == 200
    assert next(a for a in r.json()["automations"] if a["key"] == "appointment_confirmation")["max_per_run"] is None
    ma.run_tick(db)
    assert sum(len(_sends(db, c, ma.CONFIRMATION)) for c in patients) == 3

    r = client.patch("/automations/appointment_confirmation", json={"max_per_run": 0}, headers=admin_headers)
    assert r.status_code == 422


def test_attention_list_ignores_skipped_channel_when_another_delivered(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    delivered = _customer(client, auth_headers, phone=None)
    unreachable = _customer(client, auth_headers, email=None, phone=None)
    event_id = _event(client, auth_headers)
    _book(client, auth_headers, event_id, delivered, start="10:00", end="10:30")
    _book(client, auth_headers, event_id, unreachable, start="10:30", end="11:00")
    ma.run_tick(db)

    r = client.get("/automations/sends", params={"attention": True}, headers=auth_headers)
    flagged = {s["customer_id"] for s in r.json()}
    assert delivered not in flagged
    assert unreachable in flagged


def test_email_needs_no_consent_but_respects_opt_out(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    lead = _customer(client, auth_headers)  # nothing recorded beyond the email address
    opted_out = _customer(client, auth_headers, can_contact=False)
    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [send] = _sends(db, lead, ma.FOLLOWUP)
    assert send.channel == "email" and send.status == "queued"
    [skip] = _sends(db, opted_out, ma.FOLLOWUP)
    assert skip.status == "skipped" and skip.reason == "Lead has opted out of contact"


def test_whatsapp_needs_no_consent_only_a_valid_number(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, email_enabled=False, whatsapp_enabled=True)
    lead = _customer(client, auth_headers, email=None)  # nothing recorded beyond the phone number
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, lead, ma.FOLLOWUP)
    assert send.channel == "whatsapp" and send.status == "queued"


def test_plain_text_email_template_is_formatted_and_variables_unescaped(client, db, auth_headers, admin_headers, templates):
    plain = _template(
        client, admin_headers, "email",
        "Hi {{first_name}},\n\n*Date:* {{appointment_date}}\n*Where:* {{appointment_location}}\n\nCall {{clinic_phone}}",
        subject="Your Health Clinic appointment is confirmed",
    )
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, email_template_id=plain)
    r = client.patch(f"/events/{_event(client, auth_headers, location='Smith & Sons Clinic, London')}", json={}, headers=auth_headers)
    event_id = r.json()["id"]
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert "<p>Hi Pat,</p>" in send.rendered_body
    assert "<b>Where:</b> Smith &amp; Sons Clinic, London" in send.rendered_body
    [msg] = _outbound(db, cid)
    # The worker escapes plain-text templates itself, so variables go unescaped.
    assert msg.variables["appointment_location"] == "Smith & Sons Clinic, London"


# ---------------------------------------------------------------------------
# Event bookings: {{event_date}}, {{slot}}, {{event_venue}}, {{first_name}}
# ---------------------------------------------------------------------------

EVENT_FIELDS_EMAIL = (
    "Hi {{first_name}},\n\n*Date:* {{event_date}}\n*Time:* {{slot}}\n*Venue:* {{event_venue}}\n\nCall {{clinic_phone}}"
)
SLOT_TEXT = f"10:00 to 10:30 (UK time, {UK_TZ_NAME})"
DATE_TEXT = f"{DAY:%A} {DAY.day} {DAY:%B %Y}"
VENUE = "Health Clinic, 1 Harley Street, London"


def _event_field_templates(client, admin_headers):
    email = _template(client, admin_headers, "email", EVENT_FIELDS_EMAIL, subject="Your Health Clinic booking is confirmed")
    whatsapp = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}, booked: {{event_date}}, {{slot}}, {{event_venue}}", provider_template_id="HX_event")
    return email, whatsapp


def test_event_booking_confirmation_fills_event_date_slot_and_venue(client, db, auth_headers, admin_headers, templates):
    email_tpl, wa_tpl = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, email_template_id=email_tpl, whatsapp_template_id=wa_tpl)
    cid = _customer(client, auth_headers)  # "Pat Jones"
    _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)

    ma.run_tick(db)

    sends = {s.channel: s for s in _sends(db, cid, ma.CONFIRMATION)}
    body = sends["email"].rendered_body
    assert "Hi Pat," in body
    assert f"<b>Date:</b> {DATE_TEXT}" in body
    assert f"<b>Time:</b> {SLOT_TEXT}" in body
    assert f"<b>Venue:</b> {VENUE}" in body
    assert "{{" not in body
    wa_msg = next(m for m in _outbound(db, cid) if m.channel == "whatsapp")
    assert wa_msg.variables == {"1": "Pat", "2": DATE_TEXT, "3": SLOT_TEXT, "4": VENUE}


def test_no_confirmation_for_unbooked_lead(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    ma.run_tick(db)
    assert _sends(db, cid, ma.CONFIRMATION) == []
    assert _outbound(db, cid) == []


def test_no_confirmation_for_event_interest_without_a_slot(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    # Linked to the event on their deal, marked "appointment booked" in the pipeline and given
    # a follow-up date, but never assigned a slot in the Events tab.
    r = client.post(f"/customers/{cid}/deals", json={"amount": 0, "status": "open", "event_id": event_id, "seminar_preference": "London day"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert client.post(f"/inbox/customers/{cid}/stage", json={"stage": "appointment_booked"}, headers=auth_headers).status_code == 204
    client.patch(f"/customers/{cid}", json={"next_follow_up_at": (_now() + timedelta(days=3)).isoformat()}, headers=auth_headers)

    ma.run_tick(db)

    assert _sends(db, cid, ma.CONFIRMATION) == []
    assert _outbound(db, cid) == []
    # A manual confirmation using booking fields is refused with a clear reason, not sent blank.
    r = client.post(f"/customers/{cid}/email/confirmation/send", json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL}, headers=auth_headers)
    assert r.status_code == 400
    assert "linked to the event 'London consultation days' but has no booked time slot" in r.json()["detail"]


def test_appointments_only_exist_as_event_bookings(db):
    # There is no "generic" appointment in this CRM: every appointment row is a booking into an event.
    assert Appointment.__table__.c.event_id.nullable is False


def test_cancelled_booking_gets_no_confirmation(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    r = client.post(f"/events/{event_id}/appointments",
                    json={"customer_id": cid, "starts_at": f"{DAY}T10:00:00", "ends_at": f"{DAY}T10:30:00", "status": "cancelled"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    ma.run_tick(db)
    assert _sends(db, cid, ma.CONFIRMATION) == []


def test_manual_confirmation_email_uses_the_event_booking(client, db, auth_headers, monkeypatch):
    sent = {}

    class Recorder:
        def send_email(self, *, to_email, subject, body):
            sent["body"] = body
            return "rec-evt"

    monkeypatch.setattr("app.api.emails._get_email_provider", lambda: Recorder())
    cid = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)

    r = client.post(f"/customers/{cid}/email/confirmation/preview", json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert f"*Date:* {DATE_TEXT}\n*Time:* {SLOT_TEXT}\n*Venue:* {VENUE}" in r.json()["body"]

    r = client.post(f"/customers/{cid}/email/confirmation/send", json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL}, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert DATE_TEXT in sent["body"] and SLOT_TEXT in sent["body"] and VENUE in sent["body"]


def test_manual_confirmation_refused_after_booking_cancelled(client, auth_headers):
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    appt_id = _book(client, auth_headers, event_id, cid)
    client.patch(f"/events/{event_id}/appointments/{appt_id}", json={"status": "cancelled"}, headers=auth_headers)

    r = client.post(f"/customers/{cid}/email/confirmation/preview", json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL}, headers=auth_headers)
    assert r.status_code == 400
    assert "booked time slot" in r.json()["detail"]


def test_unknown_field_in_manual_email_is_refused(client, auth_headers):
    cid = _customer(client, auth_headers)
    r = client.post(f"/customers/{cid}/email/send", json={"subject": "Hi", "body": "See you on {{event_dat}}"}, headers=auth_headers)
    assert r.status_code == 400 and "{{event_dat}}" in r.json()["detail"]


def test_message_fields_endpoint_for_whatsapp_quick_message(client, auth_headers):
    booked = _customer(client, auth_headers)
    _book(client, auth_headers, _event(client, auth_headers, location=VENUE), booked)
    lead = _customer(client, auth_headers)

    r = client.get(f"/customers/{booked}/message-fields", headers=auth_headers).json()
    assert r["booking_problem"] is None
    assert (r["values"]["first_name"], r["values"]["event_date"], r["values"]["slot"], r["values"]["event_venue"]) == ("Pat", DATE_TEXT, SLOT_TEXT, VENUE)
    r = client.get(f"/customers/{lead}/message-fields", headers=auth_headers).json()
    assert r["values"]["slot"] == "" and "isn't booked into an upcoming event slot" in r["booking_problem"]


def test_venue_removed_after_queueing_cancels_then_flags_then_sends_when_fixed(client, db, auth_headers, admin_headers, templates):
    email_tpl, _wa = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, email_template_id=email_tpl)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    assert [s.status for s in _sends(db, cid, ma.CONFIRMATION)] == ["queued"]

    client.patch(f"/events/{event_id}", json={"location": ""}, headers=auth_headers)
    ma.run_tick(db)
    statuses = [(s.revision, s.channel, s.status) for s in _sends(db, cid, ma.CONFIRMATION)]
    assert statuses == [(1, "email", "cancelled"), (2, None, "needs_review")]
    assert [m.status for m in _outbound(db, cid)] == ["cancelled"]

    client.patch(f"/events/{event_id}", json={"location": "Health Clinic, 2 Wimpole Street, London"}, headers=auth_headers)
    ma.run_tick(db)
    latest = _sends(db, cid, ma.CONFIRMATION)[-1]
    assert latest.status == "queued" and "2 Wimpole Street" in latest.rendered_body
    assert sorted(m.status for m in _outbound(db, cid)) == ["cancelled", "queued"]


def test_person_with_two_bookings_gets_one_confirmation_per_booking_with_its_own_slot(client, db, auth_headers, admin_headers, templates):
    email_tpl, _wa = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, email_template_id=email_tpl)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    morning = _book(client, auth_headers, event_id, cid, start="10:00", end="10:30")
    afternoon = _book(client, auth_headers, event_id, cid, start="14:00", end="14:30")

    ma.run_tick(db)
    ma.run_tick(db)

    sends = {str(s.appointment_id): s for s in _sends(db, cid, ma.CONFIRMATION)}
    assert set(sends) == {morning, afternoon}
    assert f"10:00 to 10:30 (UK time, {UK_TZ_NAME})" in sends[morning].rendered_body
    assert "14:00" not in sends[morning].rendered_body
    assert f"14:00 to 14:30 (UK time, {UK_TZ_NAME})" in sends[afternoon].rendered_body
    assert len(_outbound(db, cid)) == 2

    # Moving one booking re-confirms only that booking.
    client.patch(f"/events/{event_id}/appointments/{afternoon}", json={"starts_at": f"{DAY}T15:00:00", "ends_at": f"{DAY}T15:30:00"}, headers=auth_headers)
    ma.run_tick(db)
    revisions = {(str(s.appointment_id), s.revision) for s in _sends(db, cid, ma.CONFIRMATION)}
    assert revisions == {(morning, 1), (afternoon, 1), (afternoon, 2)}


def test_manual_send_with_two_bookings_refuses_to_guess_unless_booking_given(client, auth_headers):
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    _book(client, auth_headers, event_id, cid, start="10:00", end="10:30")
    afternoon = _book(client, auth_headers, event_id, cid, start="14:00", end="14:30")

    r = client.post(f"/customers/{cid}/email/confirmation/preview", json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL}, headers=auth_headers)
    assert r.status_code == 400 and "2 upcoming event bookings" in r.json()["detail"]
    fields = client.get(f"/customers/{cid}/message-fields", headers=auth_headers).json()
    assert fields["values"]["slot"] == "" and "unclear which one" in fields["booking_problem"]

    r = client.post(f"/customers/{cid}/email/confirmation/preview",
                    json={"subject": "Confirmed", "body": EVENT_FIELDS_EMAIL, "appointment_id": afternoon}, headers=auth_headers)
    assert r.status_code == 200 and "14:00 to 14:30" in r.json()["body"]
    fields = client.get(f"/customers/{cid}/message-fields", params={"appointment_id": afternoon}, headers=auth_headers).json()
    assert fields["booking_problem"] is None and fields["values"]["slot"].startswith("14:00 to 14:30")


# ---------------------------------------------------------------------------
# WhatsApp: approved Content template required, no free-form exception
# ---------------------------------------------------------------------------


def _inbound_whatsapp_now(client, auth_headers, cid):
    r = client.post(f"/customers/{cid}/interactions", json={"channel": "whatsapp", "direction": "inbound", "content": "Hi, any news?"}, headers=auth_headers)
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("automation", ["confirmation", "followup"])
def test_whatsapp_never_sends_free_form_even_inside_24_hour_window(client, db, auth_headers, admin_headers, templates, automation):
    free_form = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}, call {{clinic_phone}}")
    cid = _customer(client, auth_headers, email=None)
    _inbound_whatsapp_now(client, auth_headers, cid)  # patient messaged us just now
    if automation == "confirmation":
        _enable_confirmation(client, admin_headers, templates, email_enabled=False, whatsapp_template_id=free_form)
        _book(client, auth_headers, _event(client, auth_headers), cid)
        ma.run_tick(db)
        [send] = _sends(db, cid, ma.CONFIRMATION)
    else:
        _enable_followup(client, admin_headers, templates, email_enabled=False, whatsapp_enabled=True, whatsapp_template_id=free_form)
        cid2 = _customer(client, auth_headers, email=None)
        _inbound_whatsapp_now(client, auth_headers, cid2)
        ma.run_tick(db, now=_now() + timedelta(hours=25))
        [send] = _sends(db, cid2, ma.FOLLOWUP)
        cid = cid2
    assert send.status == "needs_review" and "Content SID" in send.reason
    assert _outbound(db, cid) == []


def test_whatsapp_template_must_be_marked_approved(client, db, auth_headers, admin_headers, templates):
    unapproved = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}, call {{clinic_phone}}", provider_template_id="HX_pending", approved=False)
    _enable_followup(client, admin_headers, templates, email_enabled=False, whatsapp_enabled=True, whatsapp_template_id=unapproved)
    cid = _customer(client, auth_headers, email=None)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "needs_review" and "isn't marked as approved" in send.reason
    assert _outbound(db, cid) == []


def test_editing_whatsapp_template_clears_approval(client, admin_headers):
    tid = _template(client, admin_headers, "whatsapp", "Hi {{first_name}}", provider_template_id="HX_ok")
    assert client.get(f"/templates/{tid}", headers=admin_headers).json()["provider_approved_at"]
    r = client.patch(f"/templates/{tid}", json={"body": "Hello {{first_name}}"}, headers=admin_headers)
    assert r.json()["provider_approved_at"] is None
    r = client.patch(f"/templates/{tid}", json={"provider_approved": True}, headers=admin_headers)
    assert r.json()["provider_approved_at"]
    r = client.patch(f"/templates/{tid}", json={"provider_template_id": "HX_other"}, headers=admin_headers)
    assert r.json()["provider_approved_at"] is None
    email = _template(client, admin_headers, "email", "Hi", subject="Hi")
    assert client.patch(f"/templates/{email}", json={"provider_approved": True}, headers=admin_headers).status_code == 400


def test_manual_inbox_whatsapp_reply_unaffected(client, db, auth_headers):
    # Staff replies from the Inbox are free-form, go through the worker as before, and need no template.
    cid = _customer(client, auth_headers)
    r = client.post(f"/inbox/customers/{cid}/send-text", json={"channel": "whatsapp", "body": "Thanks, see you soon"}, headers=auth_headers)
    assert r.status_code == 201
    [msg] = _outbound(db, cid)
    assert msg.status == "queued" and msg.body == "Thanks, see you soon" and msg.template_id is None


# ---------------------------------------------------------------------------
# Follow-up: what counts as contact
# ---------------------------------------------------------------------------


def test_opening_whatsapp_chat_does_not_suppress_followup(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    assert client.post(f"/inbox/customers/{cid}/whatsapp-opened", headers=auth_headers).status_code == 204
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "queued"


def test_internal_note_does_not_count_as_contact(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    client.post(f"/customers/{cid}/interactions", json={"channel": "whatsapp", "direction": "outbound", "subject": "Internal note", "content": "Check scans"}, headers=auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    assert [s.status for s in _sends(db, cid, ma.FOLLOWUP)] == ["queued"]


def _staff_queued_message(client, db, auth_headers, cid) -> uuid.UUID:
    r = client.post(f"/inbox/customers/{cid}/send-text", json={"channel": "whatsapp", "body": "Hi from the clinic"}, headers=auth_headers)
    assert r.status_code == 201
    return uuid.UUID(r.json()["id"])


def _set_message_status(db, msg_id, status):
    db.query(OutboundMessage).filter(OutboundMessage.id == msg_id).update({OutboundMessage.status: status})
    db.commit()


@pytest.mark.parametrize("staff_outcome,expected", [("sent", "skipped"), ("failed", "queued"), ("cancelled", "queued")])
def test_pending_staff_message_pauses_followup_until_its_status_changes(client, db, auth_headers, admin_headers, templates, staff_outcome, expected):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    staff_msg = _staff_queued_message(client, db, auth_headers, cid)
    later = _now() + timedelta(hours=25)

    ma.run_tick(db, now=later)
    ma.run_tick(db, now=later + timedelta(minutes=1))
    assert _sends(db, cid, ma.FOLLOWUP) == []  # paused, nothing decided yet

    _set_message_status(db, staff_msg, staff_outcome)
    ma.run_tick(db, now=later + timedelta(minutes=2))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == expected
    if expected == "skipped":
        assert send.reason == "A message to this lead has already been sent"


@pytest.mark.parametrize("staff_outcome,expected", [("sent", "cancelled"), ("failed", "queued")])
def test_queued_followup_pauses_while_staff_message_pending(client, db, auth_headers, admin_headers, templates, staff_outcome, expected):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    later = _now() + timedelta(hours=25)
    ma.run_tick(db, now=later)
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "queued"

    staff_msg = _staff_queued_message(client, db, auth_headers, cid)
    ma.run_tick(db, now=later + timedelta(minutes=1))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "paused"
    assert db.get(OutboundMessage, send.outbound_message_id).status == "held"  # the worker won't pick it up

    _set_message_status(db, staff_msg, staff_outcome)
    ma.run_tick(db, now=later + timedelta(minutes=2))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == expected
    assert db.get(OutboundMessage, send.outbound_message_id).status == ("cancelled" if expected == "cancelled" else "queued")


def test_do_not_contact_set_during_delay_stops_followup(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    client.patch(f"/customers/{cid}", json={"can_contact": False, "consent_source": "Asked not to be contacted"}, headers=auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "skipped" and send.reason == "Lead has opted out of contact"


# ---------------------------------------------------------------------------
# Recipient review: list, preview, approval, hold, exclude
# ---------------------------------------------------------------------------


def _act(client, auth_headers, action, automation_key, customer_id, appointment_id=None, note=None, preview_token=None):
    body = {"automation_key": automation_key, "customer_id": customer_id}
    if appointment_id:
        body["appointment_id"] = appointment_id
    if note:
        body["note"] = note
    if preview_token:
        body["preview_token"] = preview_token
    return client.post(f"/automations/recipients/{action}", json=body, headers=auth_headers)


def _preview(client, auth_headers, automation_key, customer_id, appointment_id=None):
    params = {"automation_key": automation_key, "customer_id": customer_id}
    if appointment_id:
        params["appointment_id"] = appointment_id
    r = client.get("/automations/recipients/preview", params=params, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _recipient(client, auth_headers, automation_key, customer_id):
    items = client.get("/automations/recipients", headers=auth_headers).json()
    return next((i for i in items if i["automation_key"] == automation_key and i["customer_id"] == customer_id), None)


def test_recipient_list_shows_event_booking_and_planned_time(client, db, auth_headers, admin_headers, templates):
    email_tpl, wa_tpl = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, email_template_id=email_tpl, whatsapp_template_id=wa_tpl, require_approval=True)
    _enable_followup(client, admin_headers, templates, delay_minutes=24 * 60)
    booked = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), booked)
    lead = _customer(client, auth_headers, phone=None)

    entry = _recipient(client, auth_headers, "appointment_confirmation", booked)
    assert entry["state"] == "scheduled" and entry["appointment_id"] == appt
    assert entry["booking"] == {"event_name": "London consultation days", "event_date": DATE_TEXT, "slot": SLOT_TEXT, "event_venue": VENUE, "problem": None}
    assert {c["channel"]: c["address"] for c in entry["channels"]} == {"email": "pat@example.com", "whatsapp": "+447700900123"}

    follow = _recipient(client, auth_headers, "lead_followup", lead)
    assert follow["state"] == "scheduled"
    planned = datetime.fromisoformat(follow["planned_at"])
    assert timedelta(hours=23, minutes=55) < planned - _now() <= timedelta(hours=24)
    assert {c["channel"]: c["status"] for c in follow["channels"]} == {"email": "ok"}


def test_preview_resolves_fields_and_sends_nothing(client, db, auth_headers, admin_headers, templates):
    email_tpl, wa_tpl = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, email_template_id=email_tpl, whatsapp_template_id=wa_tpl)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    audit_before = len(client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers).json())

    preview = _preview(client, auth_headers, "appointment_confirmation", cid, appt)
    ch = {c["channel"]: c for c in preview["channels"]}
    assert ch["email"]["subject"] == "Your Health Clinic booking is confirmed"
    assert all(v in ch["email"]["body"] for v in ("Hi Pat,", DATE_TEXT, SLOT_TEXT, VENUE)) and ch["email"]["body"].startswith("<div")
    assert ch["whatsapp"]["body"] == f"Hi Pat, booked: {DATE_TEXT}, {SLOT_TEXT}, {VENUE}"

    # Nothing was sent, queued or logged by previewing.
    db.expire_all()
    assert _sends(db, cid) == [] and _outbound(db, cid) == []
    assert len(client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers).json()) == audit_before


def test_approval_mode_keeps_messages_until_approved_then_sends_previewed_content(client, db, auth_headers, admin_headers, templates):
    email_tpl, wa_tpl = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, email_template_id=email_tpl, whatsapp_template_id=wa_tpl, require_approval=True)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    for _ in range(3):
        ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    assert {s.status for s in sends} == {"pending_approval"}
    assert _outbound(db, cid) == []  # unapproved: nothing handed to the worker
    assert _recipient(client, auth_headers, "appointment_confirmation", cid)["state"] == "awaiting_approval"

    preview = _preview(client, auth_headers, "appointment_confirmation", cid, appt)
    assert _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt).status_code == 400  # must preview first
    r = _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt, preview_token=preview["preview_token"])
    assert r.status_code == 200, r.text

    msgs = {m.channel: m for m in _outbound(db, cid)}
    assert set(msgs) == {"email", "whatsapp"} and all(m.status == "queued" for m in msgs.values())
    by_channel = {s.channel: s for s in _sends(db, cid, ma.CONFIRMATION)}
    pch = {c["channel"]: c for c in preview["channels"]}
    # The approved messages are exactly what was previewed.
    assert by_channel["email"].rendered_body == pch["email"]["body"]
    assert by_channel["email"].rendered_subject == pch["email"]["subject"]
    assert msgs["email"].variables == by_channel["email"].payload["variables"]
    assert msgs["whatsapp"].variables == {"1": "Pat", "2": DATE_TEXT, "3": SLOT_TEXT, "4": VENUE}
    actions = [a["action"] for a in client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers).json()]
    assert actions.count("automation_send.approved") == 2


def test_approval_blocked_when_booking_details_missing(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, require_approval=True)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=None)
    appt = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)

    entry = _recipient(client, auth_headers, "appointment_confirmation", cid)
    assert entry["state"] == "needs_review" and "no location" in entry["reason"] and not entry["can_approve"]
    r = _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt)
    assert r.status_code == 400 and "no location" in r.json()["detail"]
    assert _outbound(db, cid) == []


def test_venue_removed_while_awaiting_approval_prevents_approval(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, require_approval=True)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    appt = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    client.patch(f"/events/{event_id}", json={"location": ""}, headers=auth_headers)

    r = _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt)
    assert r.status_code == 400 and "no location" in r.json()["detail"]
    assert _outbound(db, cid) == []


def test_excluded_followup_is_never_sent(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    r = _act(client, auth_headers, "exclude", "lead_followup", cid, note="Spoke on Instagram")
    assert r.status_code == 200, r.text
    for hours in (25, 30, 40):
        ma.run_tick(db, now=_now() + timedelta(hours=hours))
    [entry] = _sends(db, cid, ma.FOLLOWUP)
    assert entry.status == "excluded" and "Spoke on Instagram" in entry.reason
    assert _outbound(db, cid) == []
    assert _recipient(client, auth_headers, "lead_followup", cid) is None
    assert "automation_send.excluded" in [a["action"] for a in client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers).json()]


def test_excluding_a_queued_message_cancels_it(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    ma.run_tick(db)
    assert _recipient(client, auth_headers, "appointment_confirmation", cid)["state"] == "queued"

    assert _act(client, auth_headers, "exclude", "appointment_confirmation", cid, appt).status_code == 200
    ma.run_tick(db)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "excluded"
    assert [m.status for m in _outbound(db, cid)] == ["cancelled"]


def test_excluding_unapproved_message_means_it_is_never_sent(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, require_approval=True)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    ma.run_tick(db)
    assert _act(client, auth_headers, "exclude", "appointment_confirmation", cid, appt).status_code == 200
    ma.run_tick(db)
    assert _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt).status_code == 400
    assert _outbound(db, cid) == []


def test_hold_then_release_followup(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    assert _act(client, auth_headers, "hold", "lead_followup", cid, note="Check with Dr first").status_code == 200
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    assert _outbound(db, cid) == []
    assert _recipient(client, auth_headers, "lead_followup", cid)["state"] == "held"

    assert _act(client, auth_headers, "release", "lead_followup", cid).status_code == 200
    ma.run_tick(db, now=_now() + timedelta(hours=26))
    statuses = sorted((s.channel or "round", s.status) for s in _sends(db, cid, ma.FOLLOWUP))
    assert statuses == [("email", "queued"), ("round", "resolved")]
    actions = [a["action"] for a in client.get(f"/inbox/customers/{cid}/activity", headers=auth_headers).json()]
    assert "automation_send.held" in actions and "automation_send.released" in actions


def test_hold_a_queued_message_stops_the_worker_until_released(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    ma.run_tick(db)
    assert _act(client, auth_headers, "hold", "appointment_confirmation", cid, appt).status_code == 200
    [msg] = _outbound(db, cid)
    assert msg.status == "held"
    ma.run_tick(db)
    assert _outbound(db, cid)[0].status == "held"

    assert _act(client, auth_headers, "release", "appointment_confirmation", cid, appt).status_code == 200
    assert _outbound(db, cid)[0].status == "queued"
    assert _sends(db, cid, ma.CONFIRMATION)[0].status == "queued"


def test_pausing_automation_and_approval_setting_are_audited(client, admin_headers):
    r = client.patch("/automations/lead_followup", json={"require_approval": True}, headers=admin_headers)
    assert r.status_code == 200
    assert next(a for a in r.json()["automations"] if a["key"] == "lead_followup")["require_approval"] is True
    logs = client.get("/audit-logs", params={"entity_type": "automation"}, headers=admin_headers).json()
    assert any(l["action"] == "automation.updated" and l["after"].get("require_approval") is True for l in logs)


def test_sent_and_failed_outcomes_are_recorded(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, delay_minutes=60)
    ok, bad = _customer(client, auth_headers), _customer(client, auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=2))
    _worker_result(db, _sends(db, ok, ma.FOLLOWUP)[0], "sent")
    _worker_result(db, _sends(db, bad, ma.FOLLOWUP)[0], "failed", "SMTP 550")
    ma.run_tick(db, now=_now() + timedelta(hours=2, minutes=1))
    assert "automation_send.sent" in [a["action"] for a in client.get(f"/inbox/customers/{ok}/activity", headers=auth_headers).json()]
    assert "automation_send.failed" in [a["action"] for a in client.get(f"/inbox/customers/{bad}/activity", headers=auth_headers).json()]


# ---------------------------------------------------------------------------
# Existing records (from before the automation was switched on)
# ---------------------------------------------------------------------------


def _approve_with_preview(client, auth_headers, automation_key, cid, appt=None):
    preview = _preview(client, auth_headers, automation_key, cid, appt)
    assert preview["preview_token"], preview
    r = _act(client, auth_headers, "approve", automation_key, cid, appt, preview_token=preview["preview_token"])
    assert r.status_code == 200, r.text
    return preview


def test_existing_leads_are_listed_but_only_sent_after_include_and_approval(client, db, auth_headers, admin_headers, templates):
    client.patch("/automations/lead_followup", json={"is_enabled": False}, headers=admin_headers)
    old_lead = _customer(client, auth_headers)                              # eligible, from before
    contacted = _customer(client, auth_headers)                             # not eligible: already called
    client.post(f"/customers/{contacted}/interactions", json={"channel": "call", "direction": "outbound", "content": "Called"}, headers=auth_headers)
    _enable_followup(client, admin_headers, templates)                      # automatic mode
    new_lead = _customer(client, auth_headers)                              # created after activation

    entry = _recipient(client, auth_headers, "lead_followup", old_lead)
    assert entry["state"] == "existing" and entry["can_include"] and entry["requires_approval"] and not entry["can_hold"]
    assert _recipient(client, auth_headers, "lead_followup", contacted) is None

    later = _now() + timedelta(hours=25)
    ma.run_tick(db, now=later)
    assert _outbound(db, old_lead) == []                                    # existing: never automatic
    assert [m.status for m in _outbound(db, new_lead)] == ["queued"]        # new: automatic as configured

    assert _act(client, auth_headers, "include", "lead_followup", old_lead).status_code == 200
    ma.run_tick(db, now=later + timedelta(minutes=1))
    assert [s.status for s in _sends(db, old_lead, ma.FOLLOWUP)] == ["pending_approval"]
    assert _outbound(db, old_lead) == []                                    # included but not approved: still nothing
    assert _recipient(client, auth_headers, "lead_followup", old_lead)["state"] == "awaiting_approval"

    preview = _approve_with_preview(client, auth_headers, "lead_followup", old_lead)
    [send] = _sends(db, old_lead, ma.FOLLOWUP)
    assert send.status == "queued" and send.approved_at is not None and send.rendered_body == preview["channels"][0]["body"]
    actions = [a["action"] for a in client.get(f"/inbox/customers/{old_lead}/activity", headers=auth_headers).json()]
    assert "automation_send.included" in actions and "automation_send.approved" in actions


def test_existing_unconfirmed_bookings_are_listed_for_inclusion(client, db, auth_headers, admin_headers, templates):
    email_tpl, wa_tpl = _event_field_templates(client, admin_headers)
    client.patch("/automations/appointment_confirmation", json={"is_enabled": False}, headers=admin_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    unconfirmed = _customer(client, auth_headers)
    appt = _book(client, auth_headers, event_id, unconfirmed, start="10:00", end="10:30")
    manually_confirmed = _customer(client, auth_headers)
    _book(client, auth_headers, event_id, manually_confirmed, start="11:00", end="11:30")
    client.post(f"/inbox/customers/{manually_confirmed}/mark-confirmed", json={"channel": "phone"}, headers=auth_headers)
    _enable_confirmation(client, admin_headers, templates, email_template_id=email_tpl, whatsapp_template_id=wa_tpl)

    ma.run_tick(db)
    assert _sends(db, unconfirmed) == [] and _outbound(db, unconfirmed) == []
    entry = _recipient(client, auth_headers, "appointment_confirmation", unconfirmed)
    assert entry["state"] == "existing" and entry["booking"]["slot"] == SLOT_TEXT and entry["booking"]["event_venue"] == VENUE
    assert _recipient(client, auth_headers, "appointment_confirmation", manually_confirmed) is None

    assert _act(client, auth_headers, "include", "appointment_confirmation", unconfirmed, appt).status_code == 200
    preview = _approve_with_preview(client, auth_headers, "appointment_confirmation", unconfirmed, appt)
    email = next(c for c in preview["channels"] if c["channel"] == "email")
    assert all(v in email["body"] for v in (DATE_TEXT, SLOT_TEXT, VENUE))
    assert sorted(m.channel for m in _outbound(db, unconfirmed)) == ["email", "whatsapp"]


def test_existing_records_hidden_while_automation_paused_and_include_needs_it_on(client, db, auth_headers, admin_headers, templates):
    cid = _customer(client, auth_headers)
    _enable_followup(client, admin_headers, templates)
    client.patch("/automations/lead_followup", json={"is_enabled": False}, headers=admin_headers)
    assert _recipient(client, auth_headers, "lead_followup", cid) is None
    r = _act(client, auth_headers, "include", "lead_followup", cid)
    assert r.status_code == 400 and "Switch the automation on" in r.json()["detail"]


def test_include_only_for_existing_records(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    new_lead = _customer(client, auth_headers)
    r = _act(client, auth_headers, "include", "lead_followup", new_lead)
    assert r.status_code == 400 and "existing records" in r.json()["detail"]


def test_excluding_an_existing_record_removes_it_from_the_list(client, db, auth_headers, admin_headers, templates):
    client.patch("/automations/lead_followup", json={"is_enabled": False}, headers=admin_headers)
    cid = _customer(client, auth_headers)
    _enable_followup(client, admin_headers, templates)
    assert _act(client, auth_headers, "exclude", "lead_followup", cid, note="Not interested").status_code == 200
    assert _recipient(client, auth_headers, "lead_followup", cid) is None
    assert _act(client, auth_headers, "include", "lead_followup", cid).status_code == 400


# ---------------------------------------------------------------------------
# Pipeline stage no longer matters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["contacted", "interested", "waiting_for_response"])
def test_stage_change_alone_does_not_exclude_lead(client, db, auth_headers, admin_headers, templates, stage):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    assert client.post(f"/inbox/customers/{cid}/stage", json={"stage": stage}, headers=auth_headers).status_code == 204
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    assert [s.status for s in _sends(db, cid, ma.FOLLOWUP)] == ["queued"]


# ---------------------------------------------------------------------------
# Hold is temporary; exclude removes
# ---------------------------------------------------------------------------


def test_hold_is_temporary_even_past_the_follow_up_window(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    assert _act(client, auth_headers, "hold", "lead_followup", cid).status_code == 200
    for hours in (25, 60, 120):  # well past the 48h "missed window"
        ma.run_tick(db, now=_now() + timedelta(hours=hours))
    assert _outbound(db, cid) == []
    assert _recipient(client, auth_headers, "lead_followup", cid)["can_release"]

    assert _act(client, auth_headers, "release", "lead_followup", cid).status_code == 200
    ma.run_tick(db, now=_now() + timedelta(hours=121))
    assert [m.status for m in _outbound(db, cid)] == ["queued"]


def test_hold_and_release_awaiting_approval_returns_to_approval(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, require_approval=True)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    ma.run_tick(db)
    assert _act(client, auth_headers, "hold", "appointment_confirmation", cid, appt).status_code == 200
    assert _recipient(client, auth_headers, "appointment_confirmation", cid)["state"] == "held"
    assert _act(client, auth_headers, "release", "appointment_confirmation", cid, appt).status_code == 200
    assert _recipient(client, auth_headers, "appointment_confirmation", cid)["state"] == "awaiting_approval"
    assert _outbound(db, cid) == []


# ---------------------------------------------------------------------------
# Re-check at send time against the approved preview
# ---------------------------------------------------------------------------


def _approved_confirmation(client, db, auth_headers, admin_headers, templates):
    email_tpl, _wa = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, email_template_id=email_tpl, require_approval=True)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    appt = _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    approved = _approve_with_preview(client, auth_headers, "appointment_confirmation", cid, appt)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "queued" and send.payload["booking"] == {"event_date": DATE_TEXT, "slot": SLOT_TEXT, "event_venue": VENUE}
    return cid, event_id, appt, approved["preview_token"]


@pytest.mark.parametrize("change", ["venue", "slot"])
def test_booking_changed_after_approval_is_stopped_for_reapproval(client, db, auth_headers, admin_headers, templates, change):
    cid, event_id, appt, approved_token = _approved_confirmation(client, db, auth_headers, admin_headers, templates)
    if change == "venue":
        client.patch(f"/events/{event_id}", json={"location": "Health Clinic, 2 Wimpole Street, London"}, headers=auth_headers)
        new_value = "2 Wimpole Street"
    else:
        client.patch(f"/events/{event_id}/appointments/{appt}", json={"starts_at": f"{DAY}T14:00:00", "ends_at": f"{DAY}T14:30:00"}, headers=auth_headers)
        new_value = "14:00 to 14:30"

    ma.run_tick(db)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "reapproval" and "Booking changed after this message was prepared" in send.reason
    assert [m.status for m in _outbound(db, cid)] == ["cancelled"]          # the approved content never goes out
    ma.run_tick(db)
    assert len(_outbound(db, cid)) == 1                                     # and nothing new is sent automatically
    entry = _recipient(client, auth_headers, "appointment_confirmation", cid)
    assert entry["state"] == "needs_reapproval" and entry["can_approve"]

    # The original approval doesn't carry over: the old preview no longer matches.
    r = _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt, preview_token=approved_token)
    assert r.status_code == 409 and "changed since you previewed" in r.json()["detail"]
    fresh = _approve_with_preview(client, auth_headers, "appointment_confirmation", cid, appt)
    assert new_value in fresh["channels"][0]["body"]
    msgs = sorted(_outbound(db, cid), key=lambda m: m.created_at)
    assert [m.status for m in msgs] == ["cancelled", "queued"]
    assert new_value in _sends(db, cid, ma.CONFIRMATION)[0].rendered_body


def test_approval_refused_if_message_changed_since_preview(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, require_approval=True)
    cid = _customer(client, auth_headers)
    appt = _book(client, auth_headers, _event(client, auth_headers, location=VENUE), cid)
    ma.run_tick(db)
    preview = _preview(client, auth_headers, "appointment_confirmation", cid, appt)
    _set_clinic(client, admin_headers, phone="+44 20 0000 1111")           # changes the rendered message
    r = _act(client, auth_headers, "approve", "appointment_confirmation", cid, appt, preview_token=preview["preview_token"])
    assert r.status_code == 409 and "changed since you previewed" in r.json()["detail"]
    assert _outbound(db, cid) == []


def test_auto_mode_message_is_replaced_when_venue_changes_before_sending(client, db, auth_headers, admin_headers, templates):
    email_tpl, _wa = _event_field_templates(client, admin_headers)
    _enable_confirmation(client, admin_headers, templates, whatsapp_enabled=False, email_template_id=email_tpl)
    cid = _customer(client, auth_headers)
    event_id = _event(client, auth_headers, location=VENUE)
    _book(client, auth_headers, event_id, cid)
    ma.run_tick(db)
    client.patch(f"/events/{event_id}", json={"location": "Health Clinic, 2 Wimpole Street, London"}, headers=auth_headers)
    ma.run_tick(db)
    sends = _sends(db, cid, ma.CONFIRMATION)
    assert [(s.revision, s.status) for s in sends] == [(1, "cancelled"), (2, "queued")]
    assert "2 Wimpole Street" in sends[1].rendered_body


# ---------------------------------------------------------------------------
# Worker's send-time guard (worker/app/send_guard.py)
# ---------------------------------------------------------------------------


def _load_send_guard():
    import importlib.util
    from pathlib import Path

    for candidate in (Path(__file__).resolve().parents[2] / "worker" / "app" / "send_guard.py", Path("/worker/app/send_guard.py")):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("worker_send_guard", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    pytest.skip("worker code not available")


def test_worker_guard_stops_approved_confirmation_when_venue_changed(client, db, auth_headers, admin_headers, templates, engine):
    guard = _load_send_guard()
    cid, event_id, appt, _token = _approved_confirmation(client, db, auth_headers, admin_headers, templates)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    with engine.connect() as conn:
        assert guard.check_automated_send(conn, send.outbound_message_id) is None
    client.patch(f"/events/{event_id}", json={"location": "Somewhere else"}, headers=auth_headers)
    with engine.connect() as conn:
        assert "venue changed" in guard.check_automated_send(conn, send.outbound_message_id)


def test_worker_guard_stops_held_and_ineligible_followups_but_not_manual_messages(client, db, auth_headers, admin_headers, templates, engine):
    guard = _load_send_guard()
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    ma.run_tick(db, now=_now() + timedelta(hours=25))
    [send] = _sends(db, cid, ma.FOLLOWUP)
    with engine.connect() as conn:
        assert guard.check_automated_send(conn, send.outbound_message_id) is None
    client.post(f"/customers/{cid}/interactions", json={"channel": "call", "direction": "outbound", "content": "Called"}, headers=auth_headers)
    with engine.connect() as conn:
        assert guard.check_automated_send(conn, send.outbound_message_id) == "Lead has been contacted"

    staff = _staff_queued_message(client, db, auth_headers, cid)
    with engine.connect() as conn:
        assert guard.check_automated_send(conn, staff) is None             # manual messages are never blocked

    r = _act(client, auth_headers, "hold", "lead_followup", cid)
    assert r.status_code == 200, r.text
    with engine.connect() as conn:
        assert "no longer has this message queued" in guard.check_automated_send(conn, send.outbound_message_id)


def test_message_stopped_by_worker_guard_goes_to_reapproval_on_next_check(client, db, auth_headers, admin_headers, templates):
    cid, event_id, appt, _token = _approved_confirmation(client, db, auth_headers, admin_headers, templates)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    client.patch(f"/events/{event_id}", json={"location": "Somewhere else"}, headers=auth_headers)
    _set_message_status(db, send.outbound_message_id, "held")                # what the worker does when its guard fails
    ma.run_tick(db)
    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "reapproval"
    assert db.get(OutboundMessage, send.outbound_message_id).status == "cancelled"
