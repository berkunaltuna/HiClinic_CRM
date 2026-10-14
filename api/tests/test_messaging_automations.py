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


def _template(client, admin_headers, channel: str, body: str, subject: str | None = None, provider_template_id: str | None = None) -> str:
    payload = {"channel": channel, "name": f"t_{uuid.uuid4().hex[:8]}", "body": body, "subject": subject}
    if provider_template_id:
        payload["provider_template_id"] = provider_template_id
    r = client.post("/templates", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _automations_off(client, admin_headers):
    # Settings rows live for the whole test session; start every test with both paused.
    for key in ma.AUTOMATION_KEYS:
        r = client.patch(f"/automations/{key}", json={"is_enabled": False}, headers=admin_headers)
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


def _customer(client, auth_headers, *, email="pat@example.com", phone="+44 7700 900123", email_consent=True, whatsapp_consent=None, **extra) -> str:
    r = client.post("/customers", json={"name": "Pat Jones", "email": email, "phone": phone}, headers=auth_headers)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.patch(f"/customers/{cid}", json={"email_consent": email_consent, "whatsapp_consent": whatsapp_consent, **extra}, headers=auth_headers)
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
    # Phone on file but no WhatsApp consent recorded: WhatsApp must not be used.
    cid = _customer(client, auth_headers, email_consent=True, whatsapp_consent=None)
    appt_id = _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    sends = _sends(db, cid, ma.CONFIRMATION)
    by_channel = {s.channel: s for s in sends}
    assert set(by_channel) == {"email", "whatsapp"}
    assert by_channel["whatsapp"].status == "skipped"
    assert "No WhatsApp consent recorded" in by_channel["whatsapp"].reason

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
    cid = _customer(client, auth_headers, email_consent=None, whatsapp_consent=True, phone="07700 900456")
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
    cid = _customer(client, auth_headers, whatsapp_consent=True)
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    [send] = _sends(db, cid, ma.CONFIRMATION)
    assert send.status == "needs_review" and "Content SID" in send.reason
    assert _outbound(db, cid) == []


def test_invalid_contact_details_skip_channel(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers, email=None, phone="7700900123", email_consent=True, whatsapp_consent=True)
    _book(client, auth_headers, _event(client, auth_headers), cid)

    ma.run_tick(db)

    reasons = {s.channel: (s.status, s.reason) for s in _sends(db, cid, ma.CONFIRMATION)}
    assert reasons["email"] == ("skipped", "No valid email address on file")
    assert reasons["whatsapp"][0] == "skipped" and "No valid WhatsApp number" in reasons["whatsapp"][1]
    assert _outbound(db, cid) == []


def test_opted_out_patient_gets_no_confirmation(client, db, auth_headers, admin_headers, templates):
    _enable_confirmation(client, admin_headers, templates)
    cid = _customer(client, auth_headers, whatsapp_consent=True, can_contact=False)
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


@pytest.mark.parametrize("contact", ["call", "email_logged", "whatsapp_chat_opened", "staff_queued_message"])
def test_followup_skipped_when_staff_contacted_during_delay(client, db, auth_headers, admin_headers, templates, contact):
    _enable_followup(client, admin_headers, templates)
    cid = _customer(client, auth_headers)
    if contact == "call":
        r = client.post(f"/customers/{cid}/interactions", json={"channel": "call", "direction": "outbound", "content": "Left voicemail"}, headers=auth_headers)
    elif contact == "email_logged":
        r = client.post(f"/customers/{cid}/email/send", json={"subject": "Hello", "body": "Hi there"}, headers=auth_headers)
    elif contact == "whatsapp_chat_opened":
        r = client.post(f"/inbox/customers/{cid}/whatsapp-opened", headers=auth_headers)
    else:
        r = client.post(f"/inbox/customers/{cid}/send-text", json={"channel": "whatsapp", "body": "Hi from the clinic"}, headers=auth_headers)
    assert r.status_code in (201, 204), r.text
    before = len(_outbound(db, cid))

    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [send] = _sends(db, cid, ma.FOLLOWUP)
    assert send.status == "skipped" and send.channel is None
    assert len(_outbound(db, cid)) == before


def test_followup_respects_opt_out_and_channel_consent(client, db, auth_headers, admin_headers, templates):
    _enable_followup(client, admin_headers, templates, whatsapp_enabled=True)
    opted_out = _customer(client, auth_headers, whatsapp_consent=True, can_contact=False)
    email_only = _customer(client, auth_headers, email_consent=True, whatsapp_consent=False)

    ma.run_tick(db, now=_now() + timedelta(hours=25))

    [s] = _sends(db, opted_out, ma.FOLLOWUP)
    assert s.status == "skipped" and s.reason == "Lead has opted out of contact"
    statuses = {s.channel: (s.status, s.reason) for s in _sends(db, email_only, ma.FOLLOWUP)}
    assert statuses["email"][0] == "queued"
    assert statuses["whatsapp"] == ("skipped", "Patient has not given WhatsApp consent")
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


def test_consent_change_is_stamped_and_audited(client, auth_headers):
    cid = _customer(client, auth_headers, whatsapp_consent=True, consent_source="Verbal, phone call 14 Oct")
    r = client.get(f"/customers/{cid}", headers=auth_headers)
    body = r.json()
    assert body["whatsapp_consent"] is True and body["consent_updated_at"]
    assert body["consent_source"] == "Verbal, phone call 14 Oct"


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
    # A lead with no consent is decided (skipped) but must not use up the limit.
    no_consent = _customer(client, auth_headers, email_consent=None)
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
    delivered = _customer(client, auth_headers, email_consent=True, whatsapp_consent=None)
    unreachable = _customer(client, auth_headers, email_consent=None, whatsapp_consent=None)
    event_id = _event(client, auth_headers)
    _book(client, auth_headers, event_id, delivered, start="10:00", end="10:30")
    _book(client, auth_headers, event_id, unreachable, start="10:30", end="11:00")
    ma.run_tick(db)

    r = client.get("/automations/sends", params={"attention": True}, headers=auth_headers)
    flagged = {s["customer_id"] for s in r.json()}
    assert delivered not in flagged
    assert unreachable in flagged
