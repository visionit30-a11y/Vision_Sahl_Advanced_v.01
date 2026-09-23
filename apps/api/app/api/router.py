"""Root API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    activity_center,
    auth_sessions,
    documents,
    health,
    membership_access,
    role_administration,
    tenant_administration,
    ui_settings,
    workflows,
)

api_router = APIRouter()
api_router.include_router(activity_center.router)
api_router.include_router(health.router)
api_router.include_router(auth_sessions.router)
api_router.include_router(documents.router)
api_router.include_router(documents.center_router)
api_router.include_router(membership_access.router)
api_router.include_router(role_administration.router)
api_router.include_router(tenant_administration.router)
api_router.include_router(ui_settings.router)
api_router.include_router(workflows.router)
