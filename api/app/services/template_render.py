from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass(frozen=True)
class RenderResult:
    subject: str | None
    body: str


class TemplateRenderError(ValueError):
    pass


def render_text(text: str, context: Mapping[str, Any]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        val = context.get(key)
        return "" if val is None else str(val)

    return _TOKEN_RE.sub(repl, text)


def render_template(*, subject: str | None, body: str, context: Mapping[str, Any]) -> RenderResult:
    rendered_subject = render_text(subject, context) if subject is not None else None
    rendered_body = render_text(body, context)
    return RenderResult(subject=rendered_subject, body=rendered_body)
