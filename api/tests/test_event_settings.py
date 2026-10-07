from __future__ import annotations

import uuid


def create_event(client, headers, *, days):
    r = client.post(
        "/events",
        json={
            "name": "Settings Event",
            "location": "Clinic",
            "starts_on": days[0],
            "ends_on": days[-1],
            "days": [{"day": d, "start_time": "09:00", "end_time": "17:00", "slot_minutes": 30} for d in days],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def book(client, headers, event_id, starts_at, ends_at):
    r = client.post("/customers", json={"name": f"Guest {uuid.uuid4().hex[:6]}"}, headers=headers)
    assert r.status_code == 201, r.text
    r = client.post(
        f"/events/{event_id}/appointments",
        json={"customer_id": r.json()["id"], "starts_at": starts_at, "ends_at": ends_at},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def day_id(event, day):
    return next(d["id"] for d in event["days"] if d["day"] == day)


def test_extend_single_day_hours_only_changes_that_day(client, auth_headers):
    event = create_event(client, auth_headers, days=["2026-10-09", "2026-10-10"])
    r = client.patch(f"/events/{event['id']}/days/{day_id(event, '2026-10-10')}", json={"end_time": "20:00"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["end_time"].startswith("20:00")

    days = {d["day"]: d for d in client.get(f"/events/{event['id']}", headers=auth_headers).json()["days"]}
    assert days["2026-10-10"]["end_time"].startswith("20:00")
    assert days["2026-10-09"]["end_time"].startswith("17:00")

    # The newly opened evening slot is bookable.
    book(client, auth_headers, event["id"], "2026-10-10T19:30:00", "2026-10-10T20:00:00")


def test_shrinking_hours_past_a_booking_is_blocked(client, auth_headers):
    event = create_event(client, auth_headers, days=["2026-10-10"])
    book(client, auth_headers, event["id"], "2026-10-10T16:00:00", "2026-10-10T16:30:00")
    did = day_id(event, "2026-10-10")

    r = client.patch(f"/events/{event['id']}/days/{did}", json={"end_time": "16:00"}, headers=auth_headers)
    assert r.status_code == 400
    assert "16:00" in r.json()["detail"]

    # Rejected change was not persisted.
    days = client.get(f"/events/{event['id']}", headers=auth_headers).json()["days"]
    assert days[0]["end_time"].startswith("17:00")

    # Shrinking that still covers the booking is fine.
    r = client.patch(f"/events/{event['id']}/days/{did}", json={"end_time": "16:30"}, headers=auth_headers)
    assert r.status_code == 200, r.text


def test_break_over_booking_and_invalid_ranges_rejected(client, auth_headers):
    event = create_event(client, auth_headers, days=["2026-10-10"])
    book(client, auth_headers, event["id"], "2026-10-10T12:00:00", "2026-10-10T12:30:00")
    url = f"/events/{event['id']}/days/{day_id(event, '2026-10-10')}"

    assert client.patch(url, json={"break_start_time": "12:00", "break_end_time": "13:00"}, headers=auth_headers).status_code == 400
    assert client.patch(url, json={"start_time": "18:00"}, headers=auth_headers).status_code == 400
    assert client.patch(url, json={"break_start_time": "13:00"}, headers=auth_headers).status_code == 400
    assert client.patch(url, json={"break_start_time": "13:00", "break_end_time": "14:00"}, headers=auth_headers).status_code == 200


def test_unknown_day_returns_404(client, auth_headers):
    event = create_event(client, auth_headers, days=["2026-10-10"])
    r = client.patch(f"/events/{event['id']}/days/{uuid.uuid4()}", json={"end_time": "20:00"}, headers=auth_headers)
    assert r.status_code == 404
