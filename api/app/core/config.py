from __future__ import annotations

import os
import json


def _get_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


class Settings:
    app_version: str = os.getenv("APP_VERSION", "0.0.0")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://crm:crm@db:5432/crm"
    )

    # JWT
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "dev-change-me")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_exp_minutes: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXP_MINUTES", "120")
    )

    # Admin setup (Phase 2):
    # Comma-separated list of emails that should be treated as admins at registration time.
    # Example: ADMIN_EMAILS="admin@example.com,ops@example.com"
    admin_emails: list[str] = [
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    ]


    # Email provider (Phase 3): 'fake' for dev/tests.
    email_provider: str = os.getenv('EMAIL_PROVIDER', 'fake').lower()


    # SMTP settings (Phase 3 real email - Option A Gmail app password / SMTP)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "")
    smtp_use_starttls: bool = os.getenv("SMTP_USE_STARTTLS", "true").lower() in ("1","true","yes","y","on")


    # Phase 4: WhatsApp (Twilio) + automation
    default_country_code: str = os.getenv("DEFAULT_COUNTRY_CODE", "+44")

    # Twilio (used by webhook validation; worker reads env directly)
    twilio_account_sid: str | None = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str | None = os.getenv("TWILIO_WHATSAPP_FROM")

    # Webhook signature validation requires a public URL; default OFF for local dev.
    twilio_validate_signature: bool = _get_bool("TWILIO_VALIDATE_SIGNATURE", False)
    twilio_webhook_base_url: str | None = os.getenv("TWILIO_WEBHOOK_BASE_URL")

    # Automation defaults
    automation_welcome_template_name: str = os.getenv(
        "AUTOMATION_WELCOME_TEMPLATE_NAME", "welcome"
    )
    automation_welcome_fallback_text: str = os.getenv(
        "AUTOMATION_WELCOME_FALLBACK_TEXT",
        "Thanks for contacting us. A coordinator will reply shortly.",
    )

    # Phase 4B: optional keyword-to-tag mapping for inbound messages.
    # Example: {"implant": "implant_interest", "hair": "hair_transplant"}
    _keyword_tags_raw: str = os.getenv("KEYWORD_TAGS_JSON", "{}")
    try:
        keyword_tags: dict[str, str] = json.loads(_keyword_tags_raw) if _keyword_tags_raw else {}
    except Exception:
        keyword_tags = {}


settings = Settings()
