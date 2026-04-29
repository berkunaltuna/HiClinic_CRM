from __future__ import annotations

import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol


class EmailProvider(Protocol):
    def send_email(self, *, to_email: str, subject: str, body: str) -> str:
        """Send email and return provider message id (if available)."""


@dataclass
class FakeEmailProvider:
    """Development/test provider: does not send real emails."""

    def send_email(self, *, to_email: str, subject: str, body: str) -> str:
        return f"fake-{uuid.uuid4()}"


@dataclass
class SmtpEmailProvider:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str | None = None
    use_starttls: bool = True

    def send_email(self, *, to_email: str, subject: str, body: str) -> str:
        if not self.host:
            raise RuntimeError("SMTP_HOST is not set")
        if not self.from_email:
            raise RuntimeError("SMTP_FROM_EMAIL is not set")
        if not self.username:
            raise RuntimeError("SMTP_USERNAME is not set")
        if not self.password:
            raise RuntimeError("SMTP_PASSWORD is not set")

        msg = EmailMessage()
        if self.from_name:
            msg["From"] = f"{self.from_name} <{self.from_email}>"
        else:
            msg["From"] = self.from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        # HTML body (Gmail supports). Also provide a plain-text fallback.
        msg.set_content(_strip_html_fallback(body))
        msg.add_alternative(body, subtype="html")

        # Gmail SMTP: typically port 587 + STARTTLS.
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.ehlo()
            if self.use_starttls:
                server.starttls()
                server.ehlo()
            server.login(self.username, self.password)
            server.send_message(msg)

        # SMTP doesn't reliably return a provider message id.
        return f"smtp-{uuid.uuid4()}"


def _strip_html_fallback(html: str) -> str:
    # Very small fallback for clients that only show plain text.
    # Keeps this dependency-free (no BeautifulSoup).
    import re

    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_email_provider(*, provider: str, smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
                       smtp_from_email: str, smtp_from_name: str, smtp_use_starttls: bool) -> EmailProvider:
    provider = (provider or "fake").lower()
    if provider == "smtp":
        return SmtpEmailProvider(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            from_email=smtp_from_email,
            from_name=smtp_from_name or None,
            use_starttls=smtp_use_starttls,
        )
    if provider == "fake":
        return FakeEmailProvider()
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {provider}")
