# Phase 3E — خدمة الوثائق والمرفقات المشتركة

This batch introduces one object-storage boundary and uses workflow requests as its
first consumer. It does not introduce a business module or change the workflow,
authentication, RBAC, tenant-context, or RLS contracts. PR #24 (Phase 3D) remains a
separate prerequisite; this branch is stacked on it and must not be merged to
`develop` ahead of the approved Phase 3D merge.

## Data and authorization contract

- `app.workflow_documents` contains tenant-owned metadata only: request, uploader
  membership, safe filename, media type, byte count, SHA-256, private object key, and
  creation time. The object bytes never enter PostgreSQL or permanent API-host files.
- Migration `0024_workflow_documents` gives the table `tenant_id UUID NOT NULL`,
  composite tenant/request and tenant/uploader foreign keys, `ENABLE` and `FORCE`
  RLS, and the existing `app.current_tenant_id()` predicate for both `USING` and
  `WITH CHECK`. `sahl_migrator` owns the table. `sahl_app` has `SELECT, INSERT`
  only; no direct update or delete is exposed. A check binds the private object
  key to the same tenant and document UUID. A missing context sees no rows.
- The existing typed `tenant.workflow_requests.create` permission allows the
  requester to attach a file only while a request is `draft` or `returned`. The
  existing typed `tenant.workflow_requests.read` permission allows the current
  requester or approver to list/download attachments. The service verifies the
  request participant under RLS on every read. Cross-tenant and foreign UUIDs
  return the same 404 contract.
- No public bucket URL or presigned link is issued. Backend reads the object only
  after authorization, verifies its length and SHA-256 against metadata, then
  returns it as an attachment with `nosniff` and `Cache-Control: no-store`.

## API and validation

| Operation | Path | Result |
|---|---|---|
| POST multipart field `upload` | `/workflows/requests/{request_id}/documents` | `201` metadata |
| GET | `/workflows/requests/{request_id}/documents` | metadata list |
| GET | `/workflows/requests/{request_id}/documents/{document_id}/download` | file attachment |
| GET | `/documents` | current member's accessible document metadata across workflow requests |

Upload accepts only PDF, PNG, or JPEG, with matching extension and initial file
signature, a safe filename of at most 180 characters, and 1–10 MiB of content.
It reads at most one byte beyond the limit before rejecting. Invalid input is 422;
missing/inaccessible resources are 404; a request that is no longer editable is
409; unavailable object storage is a generic 503. Failed metadata commits trigger
a best-effort compensating object deletion. The bucket must remain private, and
operations must be served over HTTPS outside loopback development/test.

Set `OBJECT_STORAGE_ENDPOINT_URL`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_REGION`,
`OBJECT_STORAGE_ACCESS_KEY`, and `OBJECT_STORAGE_SECRET_KEY` together in the
runtime environment. The service fails closed when they are absent. Credentials
must be supplied via environment/secret management, never from source, browser,
or database. A dedicated least-privilege bucket identity needs only object
put/get/delete for the configured private bucket; bucket provisioning remains an
operator responsibility. The browser receives no object-store credentials.

The UI exposes a visible Documents center in the authenticated navigation. It
lists only attachments for requests where the current tenant membership is the
requester or assigned approver; the backend filters under the current tenant's
RLS and typed read permission. The center shows the associated request and
supports authorized downloads. Requesters can open their request; approvers
can open pending approvals. Upload remains on the request panel. The center
clears and refetches after a tenant switch, with no browser persistence.

The UI also adds a compact attachment panel to requests and approval tasks. It uses
the existing design system, translations, authenticated HTTP client, CSRF, and
tenant-rotation behavior. Upload is available to the requester while editable;
the approver can read/download. Failure stays visible; browser storage is not a
document source of truth.

## Verification and deployment boundary

The HTTP S3 adapter is tested against an isolated Moto S3 server. The browser
gate uses real FastAPI and PostgreSQL plus that S3-compatible test server;
Moto is a test dependency only and not the production storage provider. The
local PostgreSQL migration/round-trip and RLS tests run against a disposable
PostgreSQL 17 cluster, not `sahl_dev`. Production deployment must provide a
durable private S3-compatible bucket and its narrow credentials. Malware scanning,
external delivery, object retention, and a generic attachment UI for future
business modules are outside this batch; they require separate contracts before
expanding accepted file types or exposing documents outside authenticated API.
