"""Workflow attachment lifecycle with tenant and participant checks on every read."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import suppress
from datetime import datetime

from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy import text

from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.errors import AppError
from app.db.tenant_transaction import tenant_transaction
from app.documents.storage import DocumentStorageUnavailable, ObjectStorage

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
CONTENT_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


class DocumentNotFound(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


class DocumentInvalid(AppError):
    code = "validation_error"
    status_code = 422
    message = "The request payload is not valid."


class DocumentConflict(AppError):
    code = "conflict"
    status_code = 409
    message = "The request conflicts with the current state."


class DocumentRecord(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    request_id: uuid.UUID
    uploaded_by_membership_id: uuid.UUID
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    created_at: datetime


def _require(grant: AuthorizationGrant, permission: Permission) -> AuthorizationGrant:
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id != PermissionId(
        permission.value
    ):
        raise AuthorizationBoundaryRequiredError()
    return grant


def _validated_filename(name: str | None, content_type: str | None, content: bytes) -> str:
    if not name or len(name) > 180 or name != name.strip():
        raise DocumentInvalid()
    if any(ord(char) < 32 or char in "/\\" for char in name):
        raise DocumentInvalid()
    if content_type not in CONTENT_EXTENSIONS:
        raise DocumentInvalid()
    extension = CONTENT_EXTENSIONS[content_type]
    if not name.lower().endswith(extension) and not (
        content_type == "image/jpeg" and name.lower().endswith(".jpeg")
    ):
        raise DocumentInvalid()
    if not 0 < len(content) <= MAX_DOCUMENT_BYTES:
        raise DocumentInvalid()
    valid = {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
    }
    if not valid[content_type]:
        raise DocumentInvalid()
    return name


class WorkflowDocumentService:
    async def upload(
        self,
        grant: AuthorizationGrant,
        request_id: uuid.UUID,
        upload: UploadFile,
        storage: ObjectStorage,
    ) -> DocumentRecord:
        grant = _require(grant, Permission.TENANT_WORKFLOW_REQUESTS_CREATE)
        content = await upload.read(MAX_DOCUMENT_BYTES + 1)
        filename = _validated_filename(upload.filename, upload.content_type, content)
        document_id = uuid.uuid7()
        key = f"{grant.tenant_context.tenant_id}/{document_id.hex}"
        stored = False
        try:
            async with tenant_transaction(grant.tenant_context) as tx:
                status = await tx.scalar(
                    text("""
                        SELECT status FROM app.workflow_requests
                        WHERE id=:request AND requester_membership_id=:member FOR UPDATE
                    """),
                    {"request": request_id, "member": grant.principal.membership_id},
                )
                if status is None:
                    raise DocumentNotFound()
                if status not in {"draft", "returned"}:
                    raise DocumentConflict()
                await storage.put(key, content, upload.content_type or "")
                stored = True
                row = (
                    await tx.execute(
                        text("""
                            INSERT INTO app.workflow_documents(
                                id,tenant_id,request_id,uploaded_by_membership_id,
                                filename,content_type,byte_size,sha256,object_key
                            ) VALUES (
                                :id,:tenant,:request,:member,:filename,:type,:size,:sha256,:key
                            ) RETURNING id,tenant_id,request_id,uploaded_by_membership_id,
                                        filename,content_type,byte_size,sha256,created_at
                        """),
                        {
                            "id": document_id,
                            "tenant": grant.tenant_context.tenant_id,
                            "request": request_id,
                            "member": grant.principal.membership_id,
                            "filename": filename,
                            "type": upload.content_type,
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "key": key,
                        },
                    )
                ).one()
            return DocumentRecord.model_validate(row._mapping)
        except Exception:  # compensate an object after any failed DB commit
            if stored:
                with suppress(AppError):
                    await storage.delete(key)
            raise

    async def list(self, grant: AuthorizationGrant, request_id: uuid.UUID) -> list[DocumentRecord]:
        grant = _require(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            participant = await tx.scalar(
                text("""
                    SELECT 1 FROM app.workflow_requests WHERE id=:request
                      AND (requester_membership_id=:member OR approver_membership_id=:member)
                """),
                {"request": request_id, "member": grant.principal.membership_id},
            )
            if participant is None:
                raise DocumentNotFound()
            rows = (
                await tx.execute(
                    text("""
                        SELECT id,tenant_id,request_id,uploaded_by_membership_id,
                               filename,content_type,byte_size,sha256,created_at
                        FROM app.workflow_documents WHERE request_id=:request
                        ORDER BY created_at,id
                    """),
                    {"request": request_id},
                )
            ).all()
        return [DocumentRecord.model_validate(row._mapping) for row in rows]

    async def download(
        self,
        grant: AuthorizationGrant,
        request_id: uuid.UUID,
        document_id: uuid.UUID,
        storage: ObjectStorage,
    ) -> tuple[DocumentRecord, bytes]:
        grant = _require(grant, Permission.TENANT_WORKFLOW_REQUESTS_READ)
        async with tenant_transaction(grant.tenant_context) as tx:
            row = (
                await tx.execute(
                    text("""
                        SELECT d.id,d.tenant_id,d.request_id,d.uploaded_by_membership_id,
                               d.filename,d.content_type,d.byte_size,d.sha256,d.created_at,
                               d.object_key
                        FROM app.workflow_documents d
                        JOIN app.workflow_requests r
                          ON r.tenant_id=d.tenant_id AND r.id=d.request_id
                        WHERE d.id=:document AND d.request_id=:request
                          AND (r.requester_membership_id=:member
                               OR r.approver_membership_id=:member)
                    """),
                    {
                        "document": document_id,
                        "request": request_id,
                        "member": grant.principal.membership_id,
                    },
                )
            ).one_or_none()
        if row is None:
            raise DocumentNotFound()
        metadata = DocumentRecord.model_validate(row._mapping)
        content = await storage.get(row.object_key)
        if (
            len(content) != metadata.byte_size
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            raise DocumentStorageUnavailable()
        return metadata, content


workflow_document_service = WorkflowDocumentService()
