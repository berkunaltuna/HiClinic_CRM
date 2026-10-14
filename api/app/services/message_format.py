"""Plain-text message formatting.

Staff write emails as plain text: blank lines separate paragraphs, *text* is bold
(the same convention WhatsApp uses) and web links become clickable. Bodies that
already contain HTML tags are sent untouched, so older HTML templates keep working.

The worker keeps an identical copy of these two functions (worker/app/worker.py);
change both together.
"""

from __future__ import annotations

import html
import re

_HTML_TAG_RE = re.compile(r"<\s*/?\s*(p|br|b|strong|i|em|u|a|div|span|ul|ol|li|h[1-6]|table|tr|td|img)\b[^>]*>", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*(\S(?:[^*\n]*?\S)?)\*")
_URL_RE = re.compile(r"(https?://[^\s<]+[^\s<.,;:!?)\]'\"])")


def looks_like_html(text: str | None) -> bool:
    return bool(_HTML_TAG_RE.search(text or ""))


def text_to_html(text: str) -> str:
    """Escape plain text and lay it out as simple, email-safe HTML."""
    paragraphs = [p for p in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip()) if p.strip()]
    out = []
    for para in paragraphs:
        safe = html.escape(para.strip(), quote=False)
        safe = _URL_RE.sub(r'<a href="\1">\1</a>', safe)
        safe = _BOLD_RE.sub(r"<b>\1</b>", safe)
        out.append("<p>" + safe.replace("\n", "<br>") + "</p>")
    return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#1f2937">' + "".join(out) + "</div>"
