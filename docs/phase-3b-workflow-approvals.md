# Phase 3B — Shared Workflow & Approvals

## Scope

Phase 3B provides one reusable, tenant-scoped workflow service. It does not add a business
module. The delivered flow is draft → pending → approved/rejected/returned. A returned request
can be revised and resubmitted. Every transition is written atomically with an append-only
movement record.

## Authorization and isolation

The typed permission catalog adds:

- `tenant.workflow_requests.create`
- `tenant.workflow_requests.read`
- `tenant.workflow_approvals.decide`

HTTP routes obtain an `AuthorizationGrant` through the central `AuthorizationService`. The
frontend permission snapshot affects navigation and controls only; FastAPI remains the authority.
Request, approval-task, and event writes run inside `tenant_transaction()`. All three tables carry
`tenant_id`, `ENABLE RLS`, `FORCE RLS`, and matching `USING`/`WITH CHECK` policies for `sahl_app`.
Composite foreign keys prevent cross-tenant requester, approver, request, task, and actor links.
The requester cannot approve their own request. Client UUIDs are selectors and foreign selectors
return the same non-disclosing not-found/conflict contracts.

`auth.workflow_approvers()` is the only new identity projection. It is `SECURITY DEFINER`, owned by
`sahl_migrator`, has `search_path=pg_catalog`, contains no dynamic SQL or tenant-context mutation,
has no `PUBLIC` execute, and exposes active memberships in the already-bound tenant only. The
runtime role receives exact `EXECUTE` and no direct identity-table grants.

## Persistence

Migration `0018_workflow_approvals` creates:

- `app.workflow_requests`: requester-owned drafts and their lifecycle/version.
- `app.workflow_approval_tasks`: one current task per submission and immutable decision outcome.
- `app.workflow_events`: chronological movement history; runtime has `SELECT, INSERT` only.

Optimistic versions protect request edits/submission and task decisions. Row locks plus conditional
updates allow exactly one concurrent decision. Return/revision cancels no history: a new task is
created on resubmission and prior tasks remain as evidence.

## HTTP contracts

- `GET /workflows/permissions`
- `GET /workflows/approvers`
- `GET|POST /workflows/requests`
- `GET|PUT /workflows/requests/{id}`
- `POST /workflows/requests/{id}/submit`
- `GET /workflows/requests/{id}/history`
- `GET /workflows/approvals/inbox`
- `POST /workflows/approvals/{id}/decision`

All responses are `Cache-Control: no-store`. Existing cookie, CSRF, Origin, expected-membership,
session rotation, and tenant-context contracts apply unchanged.

## User interface

The authenticated shell adds permission-aware `Requests` and `Approvals inbox` routes. The request
screen creates and edits drafts, explicitly selects an active approver, submits returned requests,
shows current status, and displays movement history. The inbox supports approve, reject, and return
with decision notes. Arabic/English, RTL/LTR, responsive behavior, current tokens, and the existing
design system are preserved.

## Verification contract

The blocking proof covers the complete return → revise → resubmit → approve journey against real
FastAPI and PostgreSQL, rejection, one-winner concurrent decisions, optimistic conflicts,
cross-tenant approver/IDOR denial, RLS and grants, append-only history, projection ownership,
permission-aware navigation, no secrets in browser storage/logs, migration round trip, and all
Phase 2/3A regressions.

## Local development migration 0016

`0016_security_audit_retention` requires the cluster-level inert `sahl_security_maintenance`
NOLOGIN capability. Local development must provision it through `scripts/01-setup.ps1`, which runs
the reviewed `scripts/sql/security-maintenance-role.sql` with a masked, memory-only PostgreSQL
administrator password. The migration then grants only schema `USAGE` and exact prune-function
`EXECUTE`. Do not create the role with application/migration credentials, do not grant table access,
and do not edit the development database manually.
