from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, customers, deals, followups, interactions, templates

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(deals.router)
api_router.include_router(interactions.router)
api_router.include_router(followups.router)
api_router.include_router(templates.router)
