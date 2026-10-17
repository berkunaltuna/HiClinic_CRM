"""Last check before the worker sends an automated message.

The API re-checks automated messages about once a minute; this closes the gap between
that check and the send. It mirrors the essentials of the API's rules (the worker image
doesn't include the API code) using plain SQL:

- the automation still has the message as "queued" (not held, excluded or awaiting approval);
- event confirmations: the booking is still booked, at the same time, and the event's
  venue is still what the message was rendered/approved with;
- lead follow-ups: the lead has no event booking and nobody has contacted them since.

Returns None to send, or the reason to stop. A stopped message is set to "held" so the
API's next check decides what happens (re-approval, a fresh message, or cancelling it).
Manual messages (not linked to an automation) always pass.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def check_automated_send(conn: Any, outbound_message_id: Any) -> str | None:
    send = conn.execute(
        text(
            """
            SELECT s.automation_key, s.status, s.customer_id, s.appointment_id,
                   s.slot_starts_at, s.slot_ends_at, s.payload
            FROM automation_sends s
            WHERE s.outbound_message_id = :mid
            """
        ),
        {"mid": outbound_message_id},
    ).mappings().first()
    if send is None:
        return None  # not an automated message
    if send["status"] != "queued":
        return f"Automation no longer has this message queued (status: {send['status']})"
    payload = send["payload"] or {}

    if send["automation_key"] == "appointment_confirmation":
        booking = conn.execute(
            text(
                """
                SELECT a.status, a.starts_at, a.ends_at, e.location
                FROM appointments a JOIN events e ON e.id = a.event_id
                WHERE a.id = :aid
                """
            ),
            {"aid": send["appointment_id"]},
        ).mappings().first()
        if booking is None or (booking["status"] or "").lower() not in ("booked", "confirmed"):
            return "Booking was cancelled or removed"
        if booking["starts_at"] != send["slot_starts_at"] or booking["ends_at"] != send["slot_ends_at"]:
            return "Booking time changed since this message was prepared"
        venue = ((payload.get("booking") or {}).get("event_venue"))
        if venue is not None and (booking["location"] or "").strip() != venue:
            return "Event venue changed since this message was prepared"
        return None

    if send["automation_key"] == "lead_followup":
        cid = send["customer_id"]
        if conn.execute(
            text("SELECT 1 FROM appointments WHERE customer_id = :cid AND status <> 'cancelled' LIMIT 1"), {"cid": cid}
        ).first():
            return "Lead now has an event booking"
        if conn.execute(
            text(
                """
                SELECT 1 FROM interactions
                WHERE customer_id = :cid AND direction = 'outbound'
                  AND lower(coalesce(subject, '')) <> 'internal note'
                LIMIT 1
                """
            ),
            {"cid": cid},
        ).first():
            return "Lead has been contacted"
        other = conn.execute(
            text(
                """
                SELECT status FROM outbound_messages
                WHERE customer_id = :cid AND id <> :mid
                  AND id NOT IN (SELECT outbound_message_id FROM automation_sends
                                 WHERE automation_key = 'lead_followup' AND customer_id = :cid
                                   AND outbound_message_id IS NOT NULL)
                  AND status IN ('sent', 'queued', 'sending')
                """
            ),
            {"cid": cid, "mid": outbound_message_id},
        ).scalars().all()
        if "sent" in other:
            return "A message to this lead has already been sent"
        if other:
            return "A staff message to this lead is waiting to be sent"
        return None
    return None
