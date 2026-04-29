from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Customer, OutboundMessage, Template, Workflow
from app.services.tags import add_tag_to_customer


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _match_conditions(conditions: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    """Small, backwards-compatible condition matcher for Phase 4C.

    Supported styles:
    - Flat equality dict (Phase 4C initial): {"channel": "whatsapp", "is_new_customer": true}
    - Operator suffixes:
        * field__contains: substring contains (case-sensitive)
        * field__icontains: substring contains (case-insensitive)
        * field__neq: not-equal
        * field__in: membership in a list
    """

    if not conditions:
        return True

    for raw_key, expected in (conditions or {}).items():
        key = str(raw_key)
        if "__" not in key:
            if context.get(key) != expected:
                return False
            continue

        field, op = key.split("__", 1)
        actual = context.get(field)

        if op == "neq":
            if actual == expected:
                return False
        elif op == "contains":
            if actual is None or str(expected) not in str(actual):
                return False
        elif op == "icontains":
            if actual is None:
                return False
            if str(expected).lower() not in str(actual).lower():
                return False
        elif op == "in":
            if actual not in (expected or []):
                return False
        else:
            # unknown operator -> do not match
            return False

    return True


def _resolve_template(
    db: Session,
    *,
    owner_user_id,
    template_name: str,
    channel: str = "whatsapp",
    language: str | None = None,
) -> Template | None:
    lang = (language or "und").strip() or "und"

    # Prefer requested language, then fall back to 'und'
    tpl = (
        db.query(Template)
        .filter(Template.channel == channel)
        .filter(Template.name == template_name)
        .filter(Template.language == lang)
        .first()
    )
    if tpl:
        return tpl
    if lang != "und":
        return (
            db.query(Template)
            .filter(Template.channel == channel)
            .filter(Template.name == template_name)
            .filter(Template.language == "und")
            .first()
        )
    return None


def enqueue_outbound_message(
    db: Session,
    *,
    owner_user_id,
    customer_id,
    channel: str,
    template_id=None,
    body: str | None = None,
    variables: dict[str, Any] | None = None,
    delay_minutes: int | None = None,
    cancel_on_inbound: bool = False,
) -> OutboundMessage:
    not_before = None
    if delay_minutes is not None and delay_minutes > 0:
        not_before = _now() + timedelta(minutes=int(delay_minutes))

    msg = OutboundMessage(
        owner_user_id=owner_user_id,
        customer_id=customer_id,
        channel=channel,
        status="queued",
        template_id=template_id,
        body=body,
        variables=variables,
        not_before_at=not_before,
        cancel_on_inbound=bool(cancel_on_inbound),
    )
    db.add(msg)
    return msg


def handle_event(
    db: Session,
    *,
    owner_user_id,
    event: str,
    customer_id,
    context: dict[str, Any] | None = None,
) -> list[OutboundMessage]:
    """Run workflows for an event and enqueue outbound messages.

    This is intentionally small for Phase 4C, but it is DB-driven and extensible.
    """

    ctx = context or {}
    created: list[OutboundMessage] = []

    customer: Customer | None = db.get(Customer, customer_id)

    workflows = (
        db.query(Workflow)
        .filter(Workflow.owner_user_id == owner_user_id)
        .filter(Workflow.is_enabled.is_(True))
        .filter(Workflow.trigger_event == event)
        .order_by(Workflow.created_at.asc())
        .all()
    )

    for wf in workflows:
        if not _match_conditions(wf.conditions or {}, ctx):
            continue

        actions = wf.actions or []
        for action in actions:
            a_type = (action or {}).get("type")
            if a_type == "send_template":
                tpl_name = str(action.get("template_name") or "").strip() or settings.automation_welcome_template_name
                language = action.get("language")
                variables = action.get("variables") or ctx.get("variables") or {}
                delay_minutes = action.get("delay_minutes")
                cancel_on_inbound = bool(action.get("cancel_on_inbound") or False)

                tpl = _resolve_template(
                    db,
                    owner_user_id=owner_user_id,
                    template_name=tpl_name,
                    channel="whatsapp",
                    language=language,
                )
                if tpl is None:
                    # fall back to plain text
                    msg = enqueue_outbound_message(
                        db,
                        owner_user_id=owner_user_id,
                        customer_id=customer_id,
                        channel="whatsapp",
                        body=settings.automation_welcome_fallback_text,
                        delay_minutes=delay_minutes,
                        cancel_on_inbound=cancel_on_inbound,
                    )
                    created.append(msg)
                else:
                    msg = enqueue_outbound_message(
                        db,
                        owner_user_id=owner_user_id,
                        customer_id=customer_id,
                        channel="whatsapp",
                        template_id=tpl.id,
                        variables=variables,
                        delay_minutes=delay_minutes,
                        cancel_on_inbound=cancel_on_inbound,
                    )
                    created.append(msg)

            elif a_type == "send_text":
                body = str(action.get("body") or "").strip()
                if not body:
                    body = settings.automation_welcome_fallback_text
                delay_minutes = action.get("delay_minutes")
                cancel_on_inbound = bool(action.get("cancel_on_inbound") or False)
                msg = enqueue_outbound_message(
                    db,
                    owner_user_id=owner_user_id,
                    customer_id=customer_id,
                    channel="whatsapp",
                    body=body,
                    delay_minutes=delay_minutes,
                    cancel_on_inbound=cancel_on_inbound,
                )
                created.append(msg)

            elif a_type == "add_tag":
                # Phase 4B: add a tag to the customer.
                if customer is None:
                    continue
                tag_name = str(action.get("tag") or action.get("tag_name") or "").strip()
                if not tag_name:
                    continue
                add_tag_to_customer(db, customer=customer, tag_name=tag_name, color=action.get("color"))

            elif a_type == "set_stage":
                # Phase 4B: update funnel stage.
                if customer is None:
                    continue
                stage = str(action.get("stage") or "").strip()
                if not stage:
                    continue
                customer.stage = stage

            elif a_type == "set_follow_up":
                # Reuse existing Customer.next_follow_up_at feature.
                if customer is None:
                    continue
                minutes = action.get("minutes")
                hours = action.get("hours")
                if minutes is None and hours is None:
                    continue
                total_minutes = 0
                if hours is not None:
                    total_minutes += int(hours) * 60
                if minutes is not None:
                    total_minutes += int(minutes)
                customer.next_follow_up_at = _now() + timedelta(minutes=total_minutes)

            # unknown action types are ignored (keeps Phase 4C tolerant)

    # Persist changes (messages + customer updates/tag links)
    if created or customer is not None:
        db.commit()
        for m in created:
            db.refresh(m)

    return created
