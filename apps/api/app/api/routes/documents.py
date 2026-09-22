"""Authenticated workflow attachment endpoints backed by object storage."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission
from app.documents.service import DocumentRecord, workflow_document_service
from app.documents.storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/workflows/requests/{request_id}/documents", tags=["documents"])
create_grant = require_permission(Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
read_grant = require_permission(Permission.TENANT_WORKFLOW_REQUESTS_READ)


@router.post("", response_model=DocumentRecord, status_code=201)
async def upload_document(
    request_id: uuid.UUID,
    response: Response,
    upload: Annotated[UploadFile, File()],
    grant: Annotated[AuthorizationGrant, Depends(create_grant)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> DocumentRecord:
    response.headers["Cache-Control"] = "no-store"
    return await workflow_document_service.upload(grant, request_id, upload, storage)


@router.get("", response_model=list[DocumentRecord])
async def list_documents(
    request_id: uuid.UUID,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(read_grant)],
) -> list[DocumentRecord]:
    response.headers["Cache-Control"] = "no-store"
    return await workflow_document_service.list(grant, request_id)


@router.get("/{document_id}/download")
async def download_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    grant: Annotated[AuthorizationGrant, Depends(read_grant)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    metadata, content = await workflow_document_service.download(
        grant, request_id, document_id, storage
    )
    encoded = quote(metadata.filename, safe="")
    return Response(
        content,
        media_type=metadata.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename=download; filename*=UTF-8''{encoded}",
        },
    )
