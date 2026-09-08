"""Root API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, membership_access, role_administration, ui_settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(membership_access.router)
api_router.include_router(role_administration.router)
api_router.include_router(ui_settings.router)
