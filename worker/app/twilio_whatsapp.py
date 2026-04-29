from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from twilio.rest import Client


@dataclass(frozen=True)
class TwilioSendResult:
    sid: str


class TwilioConfigError(RuntimeError):
    pass


def _get_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise TwilioConfigError(f"Missing required env var: {name}")
    return val


def _client() -> Client:
    account_sid = _get_env("TWILIO_ACCOUNT_SID")
    auth_token = _get_env("TWILIO_AUTH_TOKEN")
    return Client(account_sid, auth_token)


def send_whatsapp_text(*, to: str, body: str) -> TwilioSendResult:
    from_ = _get_env("TWILIO_WHATSAPP_FROM")
    msg = _client().messages.create(
        from_=from_,
        to=to,
        body=body,
    )
    return TwilioSendResult(sid=msg.sid)


def send_whatsapp_template(*, to: str, content_sid: str, variables: Optional[Mapping[str, Any]] = None) -> TwilioSendResult:
    from_ = _get_env("TWILIO_WHATSAPP_FROM")
    content_variables = json.dumps(variables or {})
    msg = _client().messages.create(
        from_=from_,
        to=to,
        content_sid=content_sid,
        content_variables=content_variables,
    )
    return TwilioSendResult(sid=msg.sid)
