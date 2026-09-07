"""Root API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, membership_access

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(membership_access.router)
