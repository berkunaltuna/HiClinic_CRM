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

    # CORS (needed for browser-based frontend calls)
    # Comma-separated list of allowed origins.
    # Example: CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
    cors_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if o.strip()
    ]

    # Public self-registration. Off by default: every account is CRM staff, so new accounts
    # are created by an admin (POST /users). Emails in ADMIN_EMAILS can still register,
    # which is how the first admin is bootstrapped.
    allow_public_registration: bool = _get_bool("ALLOW_PUBLIC_REGISTRATION", False)

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    # Lead visibility
    # False = legacy per-owner isolation (keeps tests/back-compat)
    # True  = shared CRM workspace where all authenticated users can view/work all leads.
    share_customers_across_users: bool = _get_bool("SHARE_CUSTOMERS_ACROSS_USERS", False)

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




    # Facebook / Meta Lead Ads webhook ingestion
    facebook_verify_token: str = os.getenv("FACEBOOK_VERIFY_TOKEN", "berk-verify")
    facebook_page_access_token: str | None = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
    facebook_app_secret: str | None = os.getenv("FACEBOOK_APP_SECRET")
    facebook_graph_api_version: str = os.getenv("FACEBOOK_GRAPH_API_VERSION", "v23.0")
    facebook_default_owner_user_id: str | None = os.getenv("FACEBOOK_DEFAULT_OWNER_USER_ID")
    facebook_validate_signature: bool = _get_bool("FACEBOOK_VALIDATE_SIGNATURE", False)

    make_webhook_secret: str | None = os.getenv("MAKE_WEBHOOK_SECRET")

    # Google Ads lead form webhook ingestion. The key is set on the lead form
    # in Google Ads and sent back in every payload as google_key.
    google_ads_webhook_key: str | None = os.getenv("GOOGLE_ADS_WEBHOOK_KEY")
    # "Send test data" in Google Ads posts is_test=true leads; ingest them
    # (tagged test_lead) so the hookup can be verified end to end.
    google_ads_accept_test_leads: bool = _get_bool("GOOGLE_ADS_ACCEPT_TEST_LEADS", True)

    # WhatsApp Cloud API webhook ingestion
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "berk-whatsapp-verify")
    whatsapp_app_secret: str | None = os.getenv("WHATSAPP_APP_SECRET")
    whatsapp_validate_signature: bool = _get_bool("WHATSAPP_VALIDATE_SIGNATURE", False)
    whatsapp_default_owner_user_id: str | None = os.getenv("WHATSAPP_DEFAULT_OWNER_USER_ID")
    whatsapp_access_token: str | None = os.getenv("WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id: str | None = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v21.0")

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

    # Messaging automations (appointment confirmation + lead follow-up). The API
    # runs a background tick that decides what to send and queues it for the worker.
    automations_scheduler_enabled: bool = _get_bool("AUTOMATIONS_SCHEDULER_ENABLED", True)
    automations_tick_seconds: int = int(os.getenv("AUTOMATIONS_TICK_SECONDS", "60"))

    # Event booking Excel/CSV import
    import_max_rows: int = int(os.getenv("IMPORT_MAX_ROWS", "1000"))
    import_max_file_size_mb: int = int(os.getenv("IMPORT_MAX_FILE_SIZE_MB", "10"))

    # Patient photo requests (see docs/patient-photos.md).
    # Only "local" is supported: a private directory outside any public/static path,
    # e.g. a docker volume. Photo bytes never go in the database.
    photo_storage_backend: str = os.getenv("PHOTO_STORAGE_BACKEND", "local").lower()
    photo_storage_dir: str = os.getenv("PHOTO_STORAGE_DIR", "/data/patient_photos")
    photo_max_file_size_mb: int = int(os.getenv("PHOTO_MAX_FILE_SIZE_MB", "15"))
    # Per upload round: a "more photos needed" round starts a fresh allowance.
    photo_max_files_per_request: int = int(os.getenv("PHOTO_MAX_FILES_PER_REQUEST", "10"))
    photo_allowed_formats: list[str] = [
        f.strip().lower()
        for f in os.getenv("PHOTO_ALLOWED_FORMATS", "jpeg,png,webp,heic").split(",")
        if f.strip()
    ]
    photo_link_ttl_hours: int = int(os.getenv("PHOTO_LINK_TTL_HOURS", "72"))
    photo_link_max_uses: int = int(os.getenv("PHOTO_LINK_MAX_USES", "10"))
    photo_portal_session_minutes: int = int(os.getenv("PHOTO_PORTAL_SESSION_MINUTES", "30"))
    # Failed link exchanges allowed per client IP within the window before a 429.
    photo_portal_max_failed_attempts: int = int(os.getenv("PHOTO_PORTAL_MAX_FAILED_ATTEMPTS", "10"))
    photo_portal_lockout_minutes: int = int(os.getenv("PHOTO_PORTAL_LOCKOUT_MINUTES", "15"))
    # Only enable behind a reverse proxy that overwrites X-Forwarded-For.
    photo_portal_trust_proxy_headers: bool = _get_bool("PHOTO_PORTAL_TRUST_PROXY_HEADERS", False)
    photo_consent_version: str = os.getenv("PHOTO_CONSENT_VERSION", "2026-10-v1")
    photo_reviewer_description: str = os.getenv(
        "PHOTO_REVIEWER_DESCRIPTION",
        "a doctor from the Health Clinic Türkiye medical team",
    )

    # Phase 4B: optional keyword-to-tag mapping for inbound messages.
    # Example: {"implant": "implant_interest", "hair": "hair_transplant"}
    _keyword_tags_raw: str = os.getenv("KEYWORD_TAGS_JSON", "{}")
    try:
        keyword_tags: dict[str, str] = json.loads(_keyword_tags_raw) if _keyword_tags_raw else {}
    except Exception:
        keyword_tags = {}


settings = Settings()
