"""Secret message variables (e.g. a patient's private photo-upload link).

The API lists such keys in variables["_redact"]. The worker uses the real values only to
render the email it sends; the contact-thread copy and the stored queue row get these
redacted values instead. Kept dependency-free so the API tests can load it directly.
"""

from __future__ import annotations

from typing import Any, Mapping

REDACTED_VALUE = "[secure link not stored]"


def redact_variables(variables: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Copy of `variables` with the keys listed in "_redact" replaced; the same object if none."""
    if not variables or not variables.get("_redact"):
        return variables
    hidden = set(variables.get("_redact") or [])
    return {k: (REDACTED_VALUE if k in hidden else v) for k, v in variables.items()}
