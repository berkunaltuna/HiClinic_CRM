from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping

import smtplib
import uuid
from email.message import EmailMessage

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.twilio_whatsapp import TwilioConfigError, send_whatsapp_template, send_whatsapp_text


POLL_INTERVAL_SECONDS = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
MAX_RETRIES = int(os.getenv("WORKER_MAX_RETRIES", "3"))
DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "+44")

# Email config (shared with API service)
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER", "fake") or "fake").lower()
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "")
SMTP_USE_STARTTLS = (os.getenv("SMTP_USE_STARTTLS", "true").lower() == "true")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+psycopg://crm:crm@db:5432/crm")


def _engine() -> Engine:
    return create_engine(_db_url(), pool_pre_ping=True)


def _normalise_whatsapp_to(phone: str | None) -> str | None:
    if phone is None:
        return None
    s = phone.strip()
    if not s:
        return None

    # Accept either "whatsapp:+44..." or "+44..." or "078..."
    if s.lower().startswith("whatsapp:"):
        return "whatsapp:" + s.split(":", 1)[1].strip()

    if s.startswith("+"):
        return f"whatsapp:{s}"

    # crude local-number fallback: strip spaces and leading 0, prefix default country code
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    return f"whatsapp:{DEFAULT_COUNTRY_CODE}{digits}"


def _render_text(text_tpl: str, context: Mapping[str, Any]) -> str:
    # very small renderer: replaces {{key}} with context[key]
    out = text_tpl
    for k, v in context.items():
        out = out.replace("{{" + str(k) + "}}", "" if v is None else str(v))
    return out


def _strip_html_fallback(html: str) -> str:
    import re

    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _send_email(*, to_email: str, subject: str, body_html: str) -> str:
    """Send email via SMTP or fake provider (dev).

    Returns a provider_message_id string.
    """
    if EMAIL_PROVIDER == "fake":
        return f"fake-{uuid.uuid4()}"
    if EMAIL_PROVIDER != "smtp":
        raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {EMAIL_PROVIDER}")

    if not SMTP_HOST:
        raise RuntimeError("SMTP_HOST is not set")
    if not SMTP_FROM_EMAIL:
        raise RuntimeError("SMTP_FROM_EMAIL is not set")
    if not SMTP_USERNAME:
        raise RuntimeError("SMTP_USERNAME is not set")
    if not SMTP_PASSWORD:
        raise RuntimeError("SMTP_PASSWORD is not set")

    msg = EmailMessage()
    if SMTP_FROM_NAME:
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    else:
        msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(_strip_html_fallback(body_html))
    msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        if SMTP_USE_STARTTLS:
            server.starttls()
            server.ehlo()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

    return f"smtp-{uuid.uuid4()}"


def process_once(engine: Engine) -> int:
    processed = 0
    with engine.begin() as conn:
        # Wait for DB migrations to create required tables.
        exists = conn.execute(text("SELECT to_regclass('public.outbound_messages')")).scalar()
        if not exists:
            print("[worker] waiting for migrations (outbound_messages missing)")
            time.sleep(2)
            return 0
        rows = conn.execute(
            text(
                """
                SELECT id, owner_user_id, customer_id, channel, template_id, body, variables, retry_count
                FROM outbound_messages
                WHERE status = 'queued'
                  AND (not_before_at IS NULL OR not_before_at <= now())
                  AND retry_count < :max_retries
                ORDER BY created_at ASC
                LIMIT 10
                """
            ),
            {"max_retries": MAX_RETRIES},
        ).mappings().all()

    for row in rows:
        msg_id = row["id"]
        processed += 1

        # claim the job
        with engine.begin() as conn:
            updated = conn.execute(
                text(
                    """
                    UPDATE outbound_messages
                    SET status = 'sending', updated_at = now()
                    WHERE id = :id AND status = 'queued'
                    """
                ),
                {"id": msg_id},
            ).rowcount
        if updated != 1:
            continue  # someone else took it

        try:
            # fetch customer contact fields
            with engine.begin() as conn:
                customer = conn.execute(
                    text(
                        """
                        SELECT name, email, phone, company, can_contact
                        FROM customers
                        WHERE id = :cid
                        """
                    ),
                    {"cid": row["customer_id"]},
                ).mappings().first()

            if not customer:
                raise RuntimeError("Customer not found")
            if customer["can_contact"] is False:
                raise RuntimeError("Customer consent is disabled (can_contact=false)")
            channel = (row["channel"] or "").lower()

            provider_sid = None
            interaction_content = None
            interaction_subject = None

            # Shared template variables (always available)
            base_ctx: dict[str, Any] = {
                "customer_name": customer.get("name"),
                "company": customer.get("company"),
            }

            if channel == "whatsapp":
                to = _normalise_whatsapp_to(customer["phone"])
                if not to:
                    raise RuntimeError("Customer has no phone number to send WhatsApp to")

                if row["template_id"] is not None:
                    with engine.begin() as conn:
                        tpl = conn.execute(
                            text(
                                """
                                SELECT name, body, provider_template_id
                                FROM templates
                                WHERE id = :tid
                                """
                            ),
                            {"tid": row["template_id"]},
                        ).mappings().first()
                    if not tpl:
                        raise RuntimeError("Template not found")

                    variables = row["variables"] or {}
                    if tpl["provider_template_id"]:
                        res = send_whatsapp_template(
                            to=to,
                            content_sid=tpl["provider_template_id"],
                            variables=variables,
                        )
                        provider_sid = res.sid
                        interaction_content = f"[template:{tpl['name']}] {variables}"
                    else:
                        body = _render_text(tpl["body"], {**base_ctx, **variables})
                        res = send_whatsapp_text(to=to, body=body)
                        provider_sid = res.sid
                        interaction_content = body
                else:
                    if not row["body"]:
                        raise RuntimeError("No template_id or body provided")
                    body = str(row["body"])
                    res = send_whatsapp_text(to=to, body=body)
                    provider_sid = res.sid
                    interaction_content = body

            elif channel == "email":
                to_email = (customer.get("email") or "").strip()
                if not to_email:
                    raise RuntimeError("Customer has no email address")

                if row["template_id"] is None:
                    raise RuntimeError("Email channel requires template_id")

                with engine.begin() as conn:
                    tpl = conn.execute(
                        text(
                            """
                            SELECT name, subject, body
                            FROM templates
                            WHERE id = :tid
                            """
                        ),
                        {"tid": row["template_id"]},
                    ).mappings().first()
                if not tpl:
                    raise RuntimeError("Template not found")

                variables = row["variables"] or {}
                subject = _render_text(str(tpl.get("subject") or ""), {**base_ctx, **variables}).strip()
                body_html = _render_text(str(tpl.get("body") or ""), {**base_ctx, **variables}).strip()
                if not subject:
                    raise RuntimeError("Rendered subject is empty")
                if not body_html:
                    raise RuntimeError("Rendered body is empty")

                provider_sid = _send_email(to_email=to_email, subject=subject, body_html=body_html)
                interaction_subject = subject
                interaction_content = body_html

            else:
                raise RuntimeError(f"Unsupported channel: {channel}")

            # record interaction + mark sent
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO interactions
                            (id, customer_id, owner_user_id, channel, direction, occurred_at, content, subject, provider_message_id, created_at, updated_at)
                        VALUES
                            (:interaction_id, :customer_id, :owner_user_id, :channel, 'outbound', :occurred_at, :content, :subject, :provider_message_id, now(), now())
                        """
                    ),
                    {
                        "customer_id": row["customer_id"],
                        "owner_user_id": row["owner_user_id"],
                        "occurred_at": _now(),
                        "content": interaction_content,
                        "subject": interaction_subject,
                        "provider_message_id": provider_sid,
                        "interaction_id": str(__import__("uuid").uuid4()),
                        "channel": channel,
                    },
                )

                conn.execute(
                    text(
                        """
                        UPDATE outbound_messages
                        SET status = 'sent',
                            provider_message_id = :sid,
                            last_error = NULL,
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": msg_id, "sid": provider_sid},
                )

        except TwilioConfigError as e:
            # configuration issue: fail and stop fast (no point retrying)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE outbound_messages
                        SET status='failed', last_error=:err, retry_count = retry_count + 1, updated_at=now()
                        WHERE id=:id
                        """
                    ),
                    {"id": msg_id, "err": str(e)},
                )
            raise
        except Exception as e:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE outbound_messages
                        SET status='failed', last_error=:err, retry_count = retry_count + 1, updated_at=now()
                        WHERE id=:id
                        """
                    ),
                    {"id": msg_id, "err": str(e)},
                )

    return processed


def main() -> None:
    version = os.getenv("APP_VERSION", "0.0.0")
    print(f"[worker] starting (version={version})")
    engine = _engine()

    while True:
        try:
            n = process_once(engine)
            if n:
                print(f"[worker] processed {n} outbound message(s)")
        except Exception as e:
            print(f"[worker] error: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
