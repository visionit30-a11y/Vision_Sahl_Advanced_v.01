"""Root API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    auth_sessions,
    health,
    membership_access,
    role_administration,
    ui_settings,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_sessions.router)
api_router.include_router(membership_access.router)
api_router.include_router(role_administration.router)
api_router.include_router(ui_settings.router)
