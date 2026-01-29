from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


class EmailProvider(Protocol):
    def send_email(self, *, to_email: str, subject: str, body: str) -> str:
        """Send email and return provider message id."""


@dataclass
class FakeEmailProvider:
    """Development/test provider: does not send real emails."""

    def send_email(self, *, to_email: str, subject: str, body: str) -> str:
        # Return a deterministic-looking id.
        return f"fake-{uuid.uuid4()}"
