from __future__ import annotations

from datetime import datetime, timezone


def test_inbound_whatsapp_auto_tags_workflow_and_cancellation(client, auth_headers, db):
    # Add a keyword rule at runtime (settings are module-level)
    from app.core.config import settings

    settings.keyword_tags = {"implant": "implant_interest"}

    # Create a workflow that triggers on new WhatsApp inbound and schedules a follow-up message.
    wf_payload = {
        "name": "Welcome new WhatsApp lead",
        "trigger_event": "message.received",
        "is_enabled": True,
        "conditions": {"channel": "whatsapp", "is_new_customer": True},
        "actions": [
            {"type": "add_tag", "tag": "auto_replied"},
            {"type": "set_stage", "stage": "contacted"},
            {
                "type": "send_text",
                "body": "Thanks! We'll be in touch.",
                "delay_minutes": 60,
                "cancel_on_inbound": True,
            },
        ],
    }
    r = client.post("/workflows", json=wf_payload, headers=auth_headers)
    assert r.status_code == 201, r.text

    # First inbound message creates customer + interaction and triggers workflow
    form = {
        "From": "whatsapp:+447700900123",
        "Body": "Hi, I want implant prices",
        "MessageSid": "SM111",
        "ProfileName": "Test Lead",
    }
    r = client.post(
        "/webhooks/twilio/whatsapp",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text

    # Customer should exist with tags + stage
    from app.db.models import Customer, OutboundMessage

    customer = db.query(Customer).filter(Customer.phone == "+447700900123").first()
    assert customer is not None
    assert customer.stage == "contacted"
    tags = set(customer.tag_names)
    assert "whatsapp" in tags
    assert "new_lead" in tags
    assert "implant_interest" in tags
    assert "auto_replied" in tags

    # Workflow should have queued a message in the future and it must be cancellable
    msg = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.customer_id == customer.id)
        .order_by(OutboundMessage.created_at.desc())
        .first()
    )
    assert msg is not None
    assert msg.status == "queued"
    assert msg.cancel_on_inbound is True
    assert msg.not_before_at is not None
    assert msg.not_before_at > datetime.now(tz=timezone.utc)

    # Second inbound reply should cancel the queued follow-up
    form2 = {
        "From": "whatsapp:+447700900123",
        "Body": "Thanks!",
        "MessageSid": "SM112",
    }
    r = client.post(
        "/webhooks/twilio/whatsapp",
        data=form2,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text

    db.refresh(msg)
    assert msg.status == "cancelled"
