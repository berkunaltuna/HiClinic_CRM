from __future__ import annotations


def test_whatsapp_cloud_verification(client):
    from app.core.config import settings

    r = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200
    assert r.text == "12345"


def test_whatsapp_cloud_message_creates_customer_deal_and_dedupes(client, db, token):
    assert token

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "447000000000",
                                "phone_number_id": "phone-number-id",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Jane WhatsApp"},
                                    "wa_id": "447700900789",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "447700900789",
                                    "id": "wamid.test.123",
                                    "timestamp": "1777565765",
                                    "text": {"body": "Hi, I want hair transplant prices"},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    r = client.post("/webhooks/whatsapp", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processed"] == 1
    assert body["results"][0]["is_new_customer"] is True

    from app.db.models import Customer, Deal, Interaction

    customer = db.query(Customer).filter(Customer.phone == "+447700900789").first()
    assert customer is not None
    assert customer.name == "Jane WhatsApp"
    assert customer.stage == "engaged"
    assert {"whatsapp", "new_lead"}.issubset(set(customer.tag_names))

    deal = db.query(Deal).filter(Deal.customer_id == customer.id).first()
    assert deal is not None

    interaction = db.query(Interaction).filter(Interaction.provider_message_id == "wamid.test.123").first()
    assert interaction is not None
    assert interaction.channel == "whatsapp"
    assert interaction.direction == "inbound"

    r2 = client.post("/webhooks/whatsapp", json=payload)
    assert r2.status_code == 200, r2.text
    assert r2.json()["results"][0]["deduped"] is True
    assert db.query(Interaction).filter(Interaction.provider_message_id == "wamid.test.123").count() == 1
