from __future__ import annotations

from app.services.message_format import looks_like_html, text_to_html


def test_plain_text_becomes_paragraphs_line_breaks_bold_and_links():
    out = text_to_html("Hi Sarah,\n\n*Date:* 4 Nov\nJoin: https://zoom.us/j/1?a=1&b=2.\n\nThanks")
    assert "<p>Hi Sarah,</p>" in out
    assert "<p><b>Date:</b> 4 Nov<br>" in out
    assert '<a href="https://zoom.us/j/1?a=1&amp;b=2">' in out and "</a>.</p>" in out
    assert "<p>Thanks</p>" in out


def test_plain_text_is_escaped():
    out = text_to_html("Tom & Jerry <script>x</script> 5 * 3")
    assert "Tom &amp; Jerry &lt;script&gt;" in out
    assert "<b>" not in out  # a lone asterisk is not bold


def test_html_detection():
    assert looks_like_html("<p>Hi</p>")
    assert looks_like_html("Line<br>break")
    assert not looks_like_html("Hi Sarah,\n\nSee you soon")
    assert not looks_like_html("2 < 3 and <script>")


def test_manual_email_in_plain_text_is_sent_as_formatted_html(client, auth_headers, monkeypatch):
    sent = {}

    class Recorder:
        def send_email(self, *, to_email, subject, body):
            sent.update(to=to_email, subject=subject, body=body)
            return "rec-1"

    monkeypatch.setattr("app.api.emails._get_email_provider", lambda: Recorder())
    r = client.post("/customers", json={"name": "Pat Jones", "email": "pat@example.com"}, headers=auth_headers)
    cid = r.json()["id"]
    r = client.post(f"/customers/{cid}/email/send", json={"subject": "Hello", "body": "Hi {{customer_name}},\n\nSee you soon."}, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert "<p>Hi Pat Jones,</p><p>See you soon.</p>" in sent["body"]

    thread = client.get(f"/customers/{cid}/interactions", headers=auth_headers).json()
    assert thread[0]["content"] == "Hi Pat Jones,\n\nSee you soon."  # CRM thread keeps readable text


def test_manual_email_supports_automation_fields(client, auth_headers, admin_headers, monkeypatch):
    sent = {}

    class Recorder:
        def send_email(self, *, to_email, subject, body):
            sent["body"] = body
            return "rec-2"

    monkeypatch.setattr("app.api.emails._get_email_provider", lambda: Recorder())
    client.put("/automations/clinic", json={"clinic_name": "Health Clinic", "contact_phone": "+44 20 7946 0000"}, headers=admin_headers)
    cid = client.post("/customers", json={"name": "Pat Jones", "email": "pat@example.com"}, headers=auth_headers).json()["id"]
    r = client.post(f"/customers/{cid}/email/send", json={"subject": "Hi", "body": "Hi {{first_name}}, call {{clinic_phone}}"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert "Hi Pat, call +44 20 7946 0000" in sent["body"]
