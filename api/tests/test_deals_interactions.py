def test_deals_and_interactions_flow(client, auth_headers):
    # Create customer
    r = client.post(
        "/customers",
        json={"name": "Deal Customer", "email": None, "phone": None, "company": None, "next_follow_up_at": None},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    # Create deal
    r = client.post(
        f"/customers/{customer_id}/deals",
        json={"title": "Implant Package", "value": 1200, "status": "open"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    deal_id = r.json()["id"]

    # List deals
    r = client.get(f"/customers/{customer_id}/deals", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(d["id"] == deal_id for d in r.json())

    # Update deal
    r = client.patch(f"/deals/{deal_id}", json={"status": "won"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "won"

    # Create interaction
    r = client.post(
        f"/customers/{customer_id}/interactions",
        json={"channel": "email", "direction": "outbound", "content": "Sent proposal", "occurred_at": None},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    # List interactions
    r = client.get(f"/customers/{customer_id}/interactions", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(i.get("content") == "Sent proposal" for i in r.json())
