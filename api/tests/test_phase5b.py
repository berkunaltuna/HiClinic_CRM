from __future__ import annotations


def test_phase5b_outcomes_and_kpis(client, auth_headers):
    # Create a customer
    r = client.post(
        "/customers",
        json={"name": "Alice", "email": "a@example.com", "phone": "+447700900555"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    # Record an outcome
    r = client.post(
        "/outcomes",
        json={"customer_id": customer_id, "type": "consult_booked", "notes": "Booked via phone"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "consult_booked"

    # KPI summary should include the outcome
    r = client.get("/analytics/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["leads_created"] >= 1
    assert data["outcomes"].get("consult_booked", 0) >= 1
