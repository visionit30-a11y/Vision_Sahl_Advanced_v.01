"""Real PostgreSQL authorization and storage-boundary proofs for documents."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import UploadFile
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import Headers

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.documents.service import (
    DocumentInvalid,
    DocumentNotFound,
    WorkflowDocumentService,
)
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext
from app.workflow.contracts import WorkflowCreate
from app.workflow.service import WorkflowService
from tests.db.test_workflow_approvals import WorkflowFixture, grant

pytest_plugins = ["tests.db.test_workflow_approvals"]

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"


class ObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def upload(name: str = "memo.pdf", content: bytes = PDF) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": "application/pdf"}),
    )


async def create_request(state: WorkflowFixture) -> uuid.UUID:
    created = await WorkflowService().create(
        grant(state, state.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE),
        WorkflowCreate(
            request_type="general_request",
            title="Documented request",
            description="A request with an attachment",
            approver_membership_id=state.approver,
        ),
    )
    return created.id


async def test_requester_uploads_and_both_participants_read(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = WorkflowDocumentService()
    store = ObjectStore()
    request_id = await create_request(workflow_fixture)
    requester_create = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    requester_read = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    approver_read = grant(
        workflow_fixture, workflow_fixture.approver, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    created = await service.upload(requester_create, request_id, upload(), store)  # type: ignore[arg-type]
    assert created.filename == "memo.pdf"
    assert created.byte_size == len(PDF)
    assert len(store.objects) == 1
    assert [record.id for record in await service.list(requester_read, request_id)] == [created.id]
    assert [record.id for record in await service.list(approver_read, request_id)] == [created.id]
    requester_center = await service.center(requester_read)
    approver_center = await service.center(approver_read)
    assert [(item.id, item.request_title, item.relation) for item in requester_center] == [
        (created.id, "Documented request", "requester")
    ]
    assert [(item.id, item.relation) for item in approver_center] == [(created.id, "approver")]
    metadata, body = await service.download(
        approver_read,
        request_id,
        created.id,
        store,  # type: ignore[arg-type]
    )
    assert metadata.id == created.id and body == PDF


async def test_upload_validation_does_not_write_object_or_metadata(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = WorkflowDocumentService()
    store = ObjectStore()
    request_id = await create_request(workflow_fixture)
    creator = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_CREATE
    )
    for file in (
        upload("../memo.pdf"),
        upload("memo.pdf", b"not a PDF"),
        upload("memo.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024)),
    ):
        with pytest.raises(DocumentInvalid):
            await service.upload(creator, request_id, file, store)  # type: ignore[arg-type]
    assert store.objects == {}


async def test_foreign_resource_and_wrong_grant_fail_closed(
    workflow_fixture: WorkflowFixture,
) -> None:
    service = WorkflowDocumentService()
    store = ObjectStore()
    request_id = await create_request(workflow_fixture)
    requester_read = grant(
        workflow_fixture, workflow_fixture.requester, Permission.TENANT_WORKFLOW_REQUESTS_READ
    )
    foreign_grant = AuthorizationGrant(
        AuthenticatedPrincipal(
            workflow_fixture.users[2], uuid.uuid7(), workflow_fixture.foreign_member, 1
        ),
        TenantContext(TenantId(workflow_fixture.foreign_tenant)),
        PermissionId(Permission.TENANT_WORKFLOW_REQUESTS_READ.value),
    )
    with pytest.raises(DocumentNotFound):
        await service.list(foreign_grant, request_id)
    assert await service.center(foreign_grant) == []
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.center(
            grant(
                workflow_fixture,
                workflow_fixture.requester,
                Permission.TENANT_WORKFLOW_REQUESTS_CREATE,
            )
        )
    with pytest.raises(DocumentNotFound):
        await service.download(foreign_grant, request_id, uuid.uuid7(), store)  # type: ignore[arg-type]
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.upload(requester_read, request_id, upload(), store)  # type: ignore[arg-type]


def test_document_catalog_owner_rls_and_grants(
    app_connection: Connection, application_role: str, migration_role: str
) -> None:
    row = app_connection.execute(
        text("""
            SELECT pg_get_userbyid(c.relowner) AS owner, c.relrowsecurity AS rls,
                   c.relforcerowsecurity AS force_rls,
                   has_table_privilege(:app, c.oid, 'SELECT') AS can_select,
                   has_table_privilege(:app, c.oid, 'INSERT') AS can_insert,
                   has_table_privilege(:app, c.oid, 'UPDATE') AS can_update,
                   has_table_privilege(:app, c.oid, 'DELETE') AS can_delete,
                   has_table_privilege('public', c.oid, 'SELECT') AS public_select
            FROM pg_class c WHERE c.oid='app.workflow_documents'::regclass
        """),
        {"app": application_role},
    ).one()
    assert row.owner == migration_role
    assert row.rls and row.force_rls
    assert row.can_select and row.can_insert
    assert not row.can_update and not row.can_delete and not row.public_select


def test_missing_context_and_cross_tenant_sql_cannot_read_or_write(
    app_connection: Connection, workflow_fixture: WorkflowFixture
) -> None:
    assert app_connection.scalar(text("SELECT count(*) FROM app.workflow_documents")) == 0
    with pytest.raises(DBAPIError):
        app_connection.execute(
            text("""
                INSERT INTO app.workflow_documents(
                  id,tenant_id,request_id,uploaded_by_membership_id,
                  filename,content_type,byte_size,sha256,object_key
                ) VALUES (:id,:tenant,:request,:membership,'x.pdf','application/pdf',5,:hash,'x')
            """),
            {
                "id": uuid.uuid7(),
                "tenant": workflow_fixture.foreign_tenant,
                "request": uuid.uuid7(),
                "membership": workflow_fixture.foreign_member,
                "hash": "0" * 64,
            },
        )
    app_connection.rollback()


async def test_object_key_cannot_point_outside_the_current_tenant(
    app_connection: Connection, workflow_fixture: WorkflowFixture
) -> None:
    request_id = await create_request(workflow_fixture)
    app_connection.execute(
        text("SELECT set_config('app.tenant_id', CAST(:tenant AS text), true)"),
        {"tenant": workflow_fixture.tenant},
    )
    with pytest.raises(DBAPIError):
        app_connection.execute(
            text("""
                INSERT INTO app.workflow_documents(
                  id,tenant_id,request_id,uploaded_by_membership_id,
                  filename,content_type,byte_size,sha256,object_key
                ) VALUES (:id,:tenant,:request,:membership,'x.pdf','application/pdf',5,:hash,:key)
            """),
            {
                "id": uuid.uuid7(),
                "tenant": workflow_fixture.tenant,
                "request": request_id,
                "membership": workflow_fixture.requester,
                "hash": "0" * 64,
                "key": f"{workflow_fixture.foreign_tenant}/foreign-object",
            },
        )
    app_connection.rollback()
