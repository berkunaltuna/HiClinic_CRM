from __future__ import annotations

import os


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


settings = Settings()
