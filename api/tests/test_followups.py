from datetime import datetime, timedelta, timezone


def test_followups_endpoint(client, auth_headers):
    # Create customer with follow-up due (in the past)
    past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post(
        "/customers",
        json={"name": "Followup Customer", "email": None, "phone": None, "company": None, "next_follow_up_at": past},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]

    r = client.get("/followups", headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()]
    assert customer_id in ids
