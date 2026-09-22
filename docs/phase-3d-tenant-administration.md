# Phase 3D — Tenant Administration & Secure Access Bootstrap

Phase 3D adds tenant-scoped user administration without introducing a platform-wide
administrator. Every runtime decision still follows the trusted session → membership →
`TenantContext` → `AuthorizationService` → `tenant_transaction()` → PostgreSQL RLS path.

## Tenant Admin contract

Migration `0020_tenant_administration` defines one protected `tenant_admin` role kind per tenant.
Migration `0021_tenant_admin_bootstrap_fix` disambiguates the credential upsert used by the
official bootstrap boundary while preserving its owner and exact capability grant.
The official display name is `Tenant Admin / مسؤول الجمعية`. Bootstrap grants the complete current
`tenant.*` catalog and no `platform.*` permission. The role cannot be edited, disabled, or have its
permission set changed through ordinary role administration. A member cannot change their own role
assignment or membership status, and the last active Tenant Admin cannot be removed or suspended.
Assigning the protected role requires an already active Tenant Admin; custom-role permission grants
cannot exceed the actor's effective permissions.

The typed catalog adds:

- `tenant.profile.read`
- `tenant.users.read`
- `tenant.users.manage`
- `tenant.users.invite`
- `tenant.access_audit.read`
- `tenant.dashboard.read`

## Persistence and database boundaries

`app.tenant_access_events` is tenant owned, append only to the application role, and protected by
`ENABLE RLS`, `FORCE RLS`, and identical `USING`/`WITH CHECK` tenant predicates. It records safe
membership, role, and event identifiers for user invitations, membership status changes, bootstrap,
administrative password reset, and RBAC changes. Runtime receives only `SELECT, INSERT`; it cannot
update or delete the history.

The migration adds `auth.role_kind`, `auth.roles.kind`, and
`auth.password_credentials.force_password_change`. The existing RBAC table policies name
`sahl_migrator` in addition to `sahl_app` while retaining the same tenant predicate. This narrow
change lets migrator-owned `SECURITY DEFINER` functions operate under `FORCE RLS`; neither role gets
`BYPASSRLS`, and no predicate or tenant-context contract is weakened.

Runtime uses four narrowly granted functions for tenant directories, invitations, and membership
status. Bootstrap and password-reset functions are executable only by the NOLOGIN
`sahl_identity_bootstrap` capability. All are owned by `sahl_migrator`, use
`search_path=pg_catalog`, contain no dynamic SQL, have no `PUBLIC` execute, and grant no direct table
access to the capability.

## Local identity administration

Run `scripts/07-manage-local-identity.ps1` only in development. It asks for the PostgreSQL local
administrator password as a masked value, creates a short-lived login with only the bootstrap
capability, and always revokes and drops that login. The Python command prompts for email and the
new password twice; the password stays in memory, is hashed with the existing Argon2id service, and
is never accepted on the command line, printed, logged, written to a file, or committed.

Action 1 bootstraps an active user, credential, membership, protected role, permissions, assignment,
and access-history event atomically and idempotently for an explicitly selected active tenant.
Action 2 resets an existing credential using optimistic versions, can require a password change on
the next login, increments the user's security version, revokes every old session, and writes the
mandatory security event in the same transaction.

Cluster capability creation remains an explicit setup operation:
`scripts/01-setup.ps1` applies `scripts/sql/identity-bootstrap-role.sql`. Migrations grant only schema
`USAGE` and exact function execution; they never create cluster roles or expose identity tables.

## HTTP and user interface

Authenticated tenant administration exposes:

- `GET /tenant-admin/users`
- `POST /tenant-admin/users/invitations`
- `PATCH /tenant-admin/memberships/{membership_id}/status`
- `GET /tenant-admin/roles`
- `GET /tenant-admin/access-events`
- the existing typed role-assignment routes under `/auth/memberships/...`
- `POST /auth/password/change`

The application adds `/settings/users` and `/settings/password`. The users page reads only real
backend data, supports search and status filtering, invitations, activation/suspension, role
assignment/removal, and access history. Permission-aware controls improve the interface, while the
backend remains the authority. Arabic/English, RTL/LTR, responsive layout, and the existing design
system are preserved. A forced-password-change session is routed only to the password form until the
change succeeds; success revokes old sessions and returns the user to login.

## Verification contract

PostgreSQL coverage proves bootstrap idempotence, tenant-only permissions, exact capability grants,
no direct bootstrap table access, RLS isolation, append-only history, privilege-escalation denial,
self-change denial, last-admin protection, session revocation, forced-password-change projection,
cross-tenant/IDOR denial, and migration upgrade/downgrade/upgrade. Browser coverage uses real
FastAPI and PostgreSQL to prove Tenant Admin login, invitation and activation, role assignment,
ordinary-user denial, Tenant B denial, password change, old-session rejection, and login with the
new password. Platform Super Admin, global tenant administration, self-registration, and external
invitation delivery remain out of scope.
