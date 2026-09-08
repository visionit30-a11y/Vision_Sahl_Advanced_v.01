# Phase 2E G3 — Local verification

- Date: 2026-09-08.
- Branch: `codex/phase-2e-security-hardening`.
- Accepted G2 starting HEAD: `d545df6675612c400c3851e7986ebc8ffab66209`.
- Implementation commits: `161e53bbee8aa3cf86bb7c77435e148e5728d149` (redaction/logging),
  `9bf457b6b461e7cc4745d112df4b71c7fe835307` (atomic audit wiring and DB boundary).
- Migration head: `0015_security_event_wiring`.
- G3 is locally verified; G4 has not started. Phase 2E is not closed.

## Authorized changes

The user approved G3 event wiring and redaction, then explicitly approved minimal internal
login/password-change composition over existing password/session services. Four exact DB
function signatures were separately approved; no new HTTP endpoints were introduced.
Existing Authentication, AuthorizationService, TenantContext, tenant transactions, RLS policies,
FORCE RLS, UI settings and frontend contracts remain in place.

## Event coverage and atomicity

| Operation | Durable event(s) and boundary |
| --- | --- |
| Internal password authentication | `login_success` with issued session in the same transaction; anonymous `login_failure` for invalid/unknown credentials |
| Logout/current revoke/concurrent limit | `logout` or `session_revoked` once per actual state change; no duplicate HTTP emission |
| Revoke all | `all_sessions_revoked` when at least one session changes |
| Internal password change | `password_changed`, plus `all_sessions_revoked` for actual revocation, with credential/security version updates |
| Reset | `password_reset_requested`; completion atomically emits `password_reset_completed`, `password_changed`, and actual collective revocation |
| Membership/tenant switch | `membership_denied` without forged target; `tenant_switch` after trusted rotation in the same transaction |
| PostgreSQL throttling | `throttling_triggered` with atomic denied increment for the six approved scopes; no raw email/IP |
| Central HTTP enforcement | `authorization_denied`, `csrf_rejected`, `origin_rejected`; no alternate authorization decision |
| Role administration | `role_created`, `role_updated`, `role_disabled` |
| Permission links | `role_permission_assigned`, `role_permission_removed` |
| Membership-role links | `membership_role_assigned`, `membership_role_removed` |

Mandatory successful-operation events use the same connection and transaction as the mutation.
Writer failure rolls back the mutation. Idempotent no-ops emit no success event. Denials that
must survive a rolled-back request use a short audit transaction after rollback. Audit failure
preserves DENY and emits only the fixed `audit_write_failed` diagnostic; it does not claim that
an unavailable database stored an event. Foreign selectors are never recorded as proven targets.

## Role audit with unchanged RLS

`SecurityEventWriter.prepare_role()` arms an exact transaction/backend/actor/tenant/target proof.
`role_security_change_attestation` row triggers on roles, role_permissions and membership_roles
attest the actual OLD/NEW mutation executed under existing RLS. The audit insert validator
consumes that proof; deferred `role_security_event_mandatory` rejects unconsumed proofs at commit.
An attested mutation cannot be cancelled to bypass the mandatory event.

The private `auth.role_security_event_intents` table has no runtime or PUBLIC privileges and is
owned by `sahl_migrator`. It is an exact identity-security transaction-proof exception, not a
schema-wide exemption or a permission source. It has no RLS policy and no generated sequence.
Existing tenant tables retain their policies and FORCE RLS. SECDEF triggers use actual row
images rather than selecting FORCE-RLS rows with a privileged owner. Target membership checks
preserve baseline active/same-tenant requirements, including role removal.

New role-boundary functions:

- `auth.prepare_role_security_event(uuid,text,uuid,uuid,uuid,uuid,uuid,text,uuid,integer)`.
- `auth.cancel_role_security_event(uuid)`.
- `auth.attest_role_security_change()` — trigger-only.
- `auth.require_consumed_role_security_event()` — trigger-only.

Runtime EXECUTE is limited to the first two. All four have fixed `search_path=pg_catalog`,
SECURITY DEFINER and migrator ownership, no PUBLIC EXECUTE or dynamic SQL. The existing insert
validator is updated. The deferred proof guard covers wired services; raw SQL without an armed
intent retains baseline behavior. This is not a claim of auditing every administrative SQL write.

## Approved password orchestration boundary

The four approved functions are:

- `auth.password_authentication_snapshot(text)`.
- `auth.password_change_snapshot(bytea)`.
- `auth.confirm_password_authentication(uuid,bigint,bigint,text)`.
- `auth.apply_password_change(bytea,bigint,bigint,text,text)`.

Their ownership/search_path/SECDEF/EXECUTE restrictions match the role boundary. They add no
PUBLIC or direct user/credential table grants. Snapshot hashes stay inside the backend and are
excluded from repr, audit, HTTP and logs. Snapshot transactions end before Argon2 work; final
functions recheck active state, hashes and credential/security versions under locks. Existing
session/reset invalidation behavior remains atomic. Login uses the existing three HMAC throttle
paths and equivalent password work for nonexistent accounts. No Redis or authority cache exists.
`auth.complete_password_reset` adds the missing mandatory events, without delivery or auto-login.

## Redaction and correlation

Public errors project fixed code/message contracts. Validation output allows only known error
types and declared top-level schema locations; raw input, validator messages/ctx, arbitrary keys,
nested data and malformed body fragments are omitted. SQLAlchemy/driver details never form a
public message. Runtime SQLAlchemy uses `hide_parameters=True`, `echo=False`; connection URLs
are excluded from Settings repr.

Final structlog projection and the stdlib LogRecord boundary remove arbitrary messages, args,
exceptions, stacks, SQL and request bodies before handlers emit. Uvicorn and SQLAlchemy logging
use the same safe boundary. Request logs use registered route templates or `unmatched`.
Internal UUID correlation is separate from compatible client X-Request-ID echo and is cleared
on success, failure, cancellation and concurrent requests. Writer events inherit the internal
request UUID where present; DB password/reset event batches use one server-generated UUID for
the operation, never the caller's correlation text.

## Verification evidence

All final acceptance tests ran with `--strict-security-gates --tb=no`: no skip/xfail/xpass.
The complete backend suite was used at G3 acceptance to verify shared request/logging/service
boundaries against Phase 2A–2D and G2. Earlier targeted failures were corrected before acceptance.

| Gate | Final result |
| --- | --- |
| Backend full suite | **717 passed**, 52.32 seconds |
| New G3 tests included in full suite | **88**: 32 redaction + 4 session event unit + 29 auth DB + 15 role DB + 8 denial DB |
| Ruff | PASS, app/tests and new migration |
| Ruff format | Changed implementation/new tests PASS; migration uses API Ruff config |
| Mypy | PASS, 133 source files |
| Alembic check | PASS, no new upgrade operations |
| Migration | **0015 → 0014 → 0015 PASS**, existing audit row preserved unchanged |
| RLS/catalog/ownership/grants | PASS in real PostgreSQL; app owns no objects, no PUBLIC/direct audit grants |
| Post-test cleanup | PASS, no probe artifacts; seven tenant_id-bearing tables checked, including explicit exceptions |
| Private proof residue | Empty after tests, migrator ownership verified |
| Real Uvicorn emission | PASS, test-only exception probe captures final stdout/stderr and HTTP errors |
| Isolated PostgreSQL log | Tested secret markers, PHC prefix and fixture credentials absent |

Database tests used PostgreSQL 17.11 at loopback **5434**, disposable `sahl_ci`, separate runtime
and migration roles. Server statement/parameter logging was disabled in this disposable cluster;
terse server errors were checked for synthetic canaries. The cluster was stopped and its exact
owned data directory removed. Only sanitized local evidence summaries remain in ignored `_logs`.
No shared/development database configuration was changed or its data downgraded.

The real-server redaction probe used **8011** temporarily and is defined only in a test module.
It does not add a production route. Local Backend8010, Frontend5173 and browser test5187 are
unchanged; port8000 was not used. This proves tested application/Uvicorn/isolated-DB boundaries,
not an unreviewed production proxy, database server or backup policy.

## Scope and remaining work

No dependency, frontend, Design System, CI configuration, BRD/SRS or published migration edits.
The two owner reports remain untracked and excluded. No push, PR, retention deletion, cleanup
job, SIEM, Business Modules or Phase3 work. Frontend/Playwright were not rerun in this backend
G3 group; scanner/CI and complete phase-wide gates remain pending in their approved groups.

The phase matrix is **13 locally PASS / 3 PARTIAL / 6 PLANNED**, not a final phase acceptance.
There is no G3 blocker. G4 awaits approval for bounded retention capability, purge atomicity,
concurrency tests on disposable PostgreSQL, and an operational runbook. Production maintenance,
backup and log-sink claims require evidence appropriate to those environments.
