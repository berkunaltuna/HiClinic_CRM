from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    auth,
    customers,
    deals,
    followups,
    interactions,
    templates,
    emails,
    outbound_messages,
    webhooks_twilio,
    workflows,
    tags,
    inbox,
    outcomes,
    analytics,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(deals.router)
api_router.include_router(interactions.router)
api_router.include_router(followups.router)
api_router.include_router(templates.router)

api_router.include_router(emails.router)
api_router.include_router(outbound_messages.router)

# Phase 4B/4C
api_router.include_router(webhooks_twilio.router)
api_router.include_router(workflows.router)
api_router.include_router(tags.router)

# Phase 5A/5B
api_router.include_router(inbox.router)
api_router.include_router(outcomes.router)
api_router.include_router(analytics.router)
