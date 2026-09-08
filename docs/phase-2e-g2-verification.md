# Phase 2E G2 — Security audit contract verification

Date: 2026-09-08. Scope: G2 only, explicitly approved including migration 0014.
Branch: `codex/phase-2e-security-hardening`.
Baseline: `phase-2d-baseline` at `1677d114c5736c4032b862ddf0b58517490d1317`.
Implementation commits: `05385fa` (foundation), `dbae5c2` (enum validation),
`b3d2c93` (migration, runtime integration and PostgreSQL proofs).

## Contract and database boundary

- One typed catalogue: 22 event IDs, three results, 19 closed reason codes and an explicit event/result/reason mapping.
- Closed intent: UUID identities, typed PermissionId, bounded count, optional subject digest/purpose/key-ID triad. No JSON metadata or arbitrary fields, including nested secret-bearing inputs.
- Subject bytes require approved HMAC provenance from the caller; shape/length validation alone cannot prove cryptographic origin. G2 adds no subject HMAC emitter or key configuration.
- Canonical enum instances are required, including during writer revalidation. Forged enum values fail with a fixed error, without a leaking KeyError.
- Writer generates UUIDv7 event IDs and an internal correlation ID, uses the caller's open transaction and never commits independently. Database errors are replaced without rendering SQL, parameters or the exception chain.
- Existing auth HTTP audit calls now use the typed writer. Reset functions retain their authentication operations and only forward their audit INSERT to the hardened boundary.
- Database time controls created_at. Existing user/session/membership links are checked and locked until transaction end; inconsistent or foreign links are rejected, never silently replaced with NULL.
- No foreign keys or cascades remove historical audit rows after identity deletion.

Migration head: `0014_security_audit_contract`, after `0013_auth_http_projections`.
Six nullable fields: role_id, target_membership_id, permission_id, subject_kind,
subject_key_id, affected_count. New checks enforce future inserts using NOT VALID
where necessary to preserve legacy rows unchanged. This does not claim retrospective
validation or redaction of historical data.

## Functions, trigger and privileges

New exact write signature:

```sql
auth.append_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,uuid,uuid,uuid,text,text,smallint,bigint)
```

New trigger function `auth.validate_security_event_insert()` serves the
`security_event_insert_guard` BEFORE INSERT trigger. These SECURITY DEFINER functions
are necessary to validate identity links and append while runtime has no direct table
access. Owner: sahl_migrator; fixed search_path=pg_catalog; no dynamic SQL, tenant-context
mutation or RLS bypass. Runtime can execute only the append signature, not the trigger
function; PUBLIC has no execute privilege.

The existing `auth.record_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,text)`
remains a restricted compatibility wrapper. It replaces client correlation text with
an internally generated UUID. Existing request/complete reset signatures remain unchanged.

Table owner is sahl_migrator. Runtime has no SELECT, INSERT, UPDATE, DELETE, TRUNCATE,
REFERENCES or TRIGGER privilege on security_events; PUBLIC has no table privileges.
Append-only is the runtime boundary, not a tamper-proof claim against the database owner.
No default grants were broadened, and no RLS policy was modified.

## Executed evidence

PostgreSQL **17.11**, disposable database sahl_ci on **127.0.0.1:5434**.
Runtime tests: sahl_app (no ownership/superuser/BYPASSRLS); migration fixtures: sahl_migrator.
The shared development database and application ports were not used.

| Gate | Result |
| --- | --- |
| Audit domain + writer | 97 PASS |
| New PostgreSQL audit proofs | 42 PASS |
| Related Phase 2A–2D regression guards | 174 PASS |
| Final combined targeted run | **313 PASS**, 25.21 seconds, strict security gates, no skips |
| Ruff, targeted implementation/tests/migration | PASS |
| Mypy, 11 related source files | PASS |
| Alembic check | PASS; no new upgrade operations |
| 0014 → 0013 → 0014 | PASS; original legacy row preserved |
| Downgrade with a new event type | Rejected atomically; revision and event preserved |
| Runtime append-only / exact ACL / owner / PUBLIC | PASS |
| Same-transaction mandatory audit failure | Mutation rolled back; reset, switch/logout and writer paths covered |
| Concurrent session membership change | Blocked while append transaction holds its verified link; succeeds after rollback |
| Cleanup/catalog guard | PASS; no probe artifacts, six production tenant tables verified |
| Disposable PostgreSQL log canaries | No synthetic audit input, PHC or connection credentials |

Downgrade takes an ACCESS EXCLUSIVE lock before checking history compatibility, so a
concurrent append cannot slip between the check and column removal. New event types or
extension metadata cause a fixed failure; no event is deleted merely to permit downgrade.
The successful round trip used a pre-0014 row with its original legacy metadata unchanged.

Test selection: test_audit_contracts, test_audit_writer, test_security_audit_contract,
test_auth_security_controls, test_auth_transport_db, test_rls_catalog,
test_rls_attack_matrix, test_rls_pool_reuse, test_rls_runtime_ddl_denial,
test_rls_fixture_lifecycle, test_rbac_foundation, test_role_administration,
test_ui_settings_foundation, test_permission_catalog, test_tenant_transaction_contract,
test_auth_transport. The combined command used --strict-security-gates --tb=no.

The isolated cluster was stopped and its data removed after verification. Only sanitized
gate summaries remain under ignored `_logs`; no database credentials were added to commits.
No full Backend/Frontend/browser suite, scanner, dependency update, CI, push or PR was run
for G2. BRD/SRS and the two untracked owner reports remain outside these changes.

## Remaining phase work

G2 has no remaining execution blocker. Seven role events and security_events_pruned
remain reserved and rejected by both writer and database. A trusted role audit proof
compatible with the current FORCE RLS policy is required before connecting those emitters.
No retention capability, cleanup job, deletion logic or SIEM was implemented.

G3 awaits user approval: connect the remaining existing security operations to audit,
resolve the role-proof boundary without changing RLS, and harden error/validation/
exception output. G2's writer tests are not a claim that global application, proxy or
production PostgreSQL logging has already been hardened.
