# Phase 2E G4 — Bounded security audit retention

**Status: G4 operationally verified locally on disposable PostgreSQL, 2026-09-08.**
This document does not claim that retention has run or that a production environment complies.
G3 starting HEAD: `542d5da3073ab2741beb436fb7e1637da1770d1d`.

## Contract

- Keep security events for at least **90 × 24 hours**, measured by PostgreSQL `created_at`.
- `auth.prune_security_events(integer)` uses a fixed server cutoff: DB transaction-start time (`transaction_timestamp()`) minus
  `interval '2160 hours'`. A longer-held transaction can only retain records longer, never delete
  newer records. The runner opens a fresh bounded transaction for each batch. Caller supplies only batch size, from 1 through 1000.
- Rows exactly at or newer than the cutoff remain. A `(created_at,id)` index supports ordered
  selection. `FOR UPDATE SKIP LOCKED` prevents concurrent workers deleting the same row.
- Return only `deleted_count` and `remaining_expired`. Locked expired rows still count as
  remaining. Zero deletions with remaining rows means incomplete, never successful draining.
- A nonempty batch writes exactly one `security_events_pruned` / `retention_expired` event
  with actual `affected_count` and server-generated event/correlation UUIDs. No target IDs,
  row contents, client cutoff or arbitrary metadata are accepted. No-op produces no event.
- Delete and mandatory event share one transaction. Audit failure rolls back the deletion.
- No tenant transaction, RLS, RBAC, Authentication or UI Settings contract is changed.

## Capability and deployment boundary

`sahl_security_maintenance` is a NOLOGIN capability, without ownership, superuser, BYPASSRLS,
CREATEDB, CREATEROLE or REPLICATION. Provision it separately with
`scripts/sql/security-maintenance-role.sql` using an authorized database administrator.
Provisioning checks unsafe existing role attributes/membership and fails without silently
altering them. Local setup creates this inert capability only; it creates no maintenance
credential and executes no purge.

Migration `0016_security_audit_retention` grants only auth schema USAGE and
EXECUTE on `auth.prune_security_events(integer)` to the capability. All application audit
append/record functions and direct table operations remain inaccessible to it. The function
is SECURITY DEFINER, owned by `sahl_migrator`, with `search_path=pg_catalog` and no dynamic SQL
or PUBLIC EXECUTE. The migrator remains NOCREATEROLE.

A separately provisioned operational LOGIN inherits the capability; it must have no application
or migrator membership, privileged flags, project object ownership or overlapping table/function
grants. The purge function and prune-event validator both verify immutable `session_user`,
never the SECURITY DEFINER `current_user` or a caller-controlled setting. Additional append or
table grants cause fail-closed rejection, preventing forged count events through another writer.
No proof table is needed because only the narrow purge path is available to that principal.

The fixture LOGIN `sahl_maintenance_test` exists only in isolated `sahl_ci`. Its password is
generated at test bootstrap, passed through the ephemeral runner environment and never printed
or committed; it is not a production credential. No production LOGIN
or credential is created by migrations, app startup or the ordinary local setup script.

## Bounded runner contract

The command, run from `apps/api`, is:

```text
python -m app.maintenance.security_audit_retention --execute --batch-size 1000 --max-batches 10
```

The dedicated `SECURITY_MAINTENANCE_DATABASE_URL` must be supplied through the authorized job's
protected environment. It is never accepted as a command argument and never falls back to
DATABASE_URL, MIGRATION_DATABASE_URL or `.env`. Do not echo it or put its value in transcripts,
shell history, checked-in files, screenshots or artifact logs. Nonlocal operational connections
should use the approved TLS configuration, for example libpq `PGSSLMODE=verify-full` with
`PGSSLROOTCERT` supplied by deployment configuration. The URL itself accepts no query overrides.

`--execute` is explicit; omission opens no connection and performs no purge. Batch size is
1..1000 (default 1000); max batches is 1..100 (default 10). Each batch commits independently only
after a valid result. There are no automatic retries, unbounded loops or in-memory fallback.
Connection/lock/statement timeouts are bounded. Output contains only a fixed status, committed
row count and batch count; it never contains a DSN, exception message, SQL, parameters or IDs.

- Exit 0: no expired rows remain according to the last committed result.
- Exit 2: backlog or locked rows remain, including exhaustion of the batch limit.
- Exit 1: invalid configuration/input or database failure; prior batches may already be committed.

A repeated invocation is safe with respect to already deleted events. For an ambiguous commit
failure, PostgreSQL's audit record is authoritative; the command cannot claim exact completion
from an interrupted connection. Do not interpret exit 1/2 as enforcement of the retention SLA.

## Operational runbook

1. Confirm the intended database/cluster and approved role separation. Apply the capability
   provisioning before migration 0016; configure its dedicated LOGIN separately and securely.
2. Apply the migration as the existing migrator; confirm role flags, owner and exact grants.
3. A future, separately approved deployment may invoke the bounded command daily.
   No scheduler, service, cron, job deployment or automation is installed in G4.
4. Treat nonzero exit or missed daily execution as an operational failure requiring attention.
   Re-run within the documented bounded procedure after resolving contention/connectivity or
   backlog; do not silently increase privileges, remove event checks or change the cutoff.
5. Before upgrades/restores, prevent serving traffic until expired restored events are purged
   under the same capability and its completion has been checked.
6. Review real PostgreSQL/proxy log configuration and backup retention separately. The ADR's
   proposed 30-day rolling backup limit is not a claim about current infrastructure. Application
   purging cannot prove deletion from unreviewed backups, replicas or exported logs.

Downgrade0016→0015 removes the purge function/index and restores the prior validator without
altering audit history or dropping the cluster-wide capability/LOGIN. Stop the external job
before downgrade; it must then fail closed. The capability can remain inert for later upgrade.

## Required verification

Only disposable PostgreSQL is used for tests, with `APP_ENV=test`, isolated `sahl_ci` and explicit
maintenance URL. Tests must refuse any existing expired rows before creating their own fixtures.
No runtime/dev/production URL fallback, fixture purge of another environment or skipped gate.

Prove cutoff/TTL/UTC boundaries, batch limits, idempotent no-op, concurrent workers, locked-row
remaining state, exact audit counts, event-failure rollback, forbidden runtime/PUBLIC access,
no direct maintenance table/append privileges, forged GUC/SET ROLE denial, overlapping-grant
rejection, owner/search_path/catalog/index, migration round-trip and unchanged RLS guards.
Runner tests cover bounded execution, per-batch commits, missing configuration, invalid arguments,
malformed DB results, backlog/failure exit codes and secret-free stdout/stderr.

## Local acceptance evidence

Implementation commits:

- `30bdebbd7219a432c7d156148f62e494fd487cb4`: bounded database capability, index,
  provisioning and PostgreSQL privilege/retention proofs.
- `cab890593921a1b087a2b791520e515101fd4d65`: environment-only runner, unit tests,
  real runner and history-preserving migration proof.

The user explicitly approved G4, the exact function/capability/runner and isolated deletion tests
in this repository. Work stayed on `codex/phase-2e-security-hardening`; no push/PR or new branch.
Migration head is **`0016_security_audit_retention`**. Previous migrations were not edited.

| Gate | Final result |
| --- | --- |
| New PostgreSQL retention/capability proofs | **45 PASS** |
| New runner unit contracts | **54 PASS** |
| New isolated CI fixture / secret-emission unit proofs | **7 PASS** |
| New real PostgreSQL runner and migration proofs | **6 PASS** |
| Existing Phase 2A–2D / G2–G3 PostgreSQL security regressions | **292 PASS** |
| Unique targeted tests | **404 PASS**, including **112 new G4 tests** |
| Ruff / format | PASS |
| Mypy | PASS, 139 application/test source files + isolated CI fixture |
| Alembic check | PASS, no new upgrade operations detected |
| Migration round-trip | **0016 → 0015 → 0016 PASS**; all retained audit JSON and capability identity preserved |
| Ownership / grants / RLS / catalog | PASS |
| Post-test cleanup | PASS, no probe artifacts; seven tenant_id-bearing tables checked, including approved exceptions |
| Local setup PowerShell syntax | PASS; local development setup was not executed |

All selected tests used `--strict-security-gates`: no skip/xfail/xpass. The database was real
PostgreSQL17 on **127.0.0.1:5434**, disposable **sahl_ci**, with separate migrator, application
and maintenance test sessions. The runtime-generated maintenance password stayed in harness
memory, never in a source file, environment file, transcript or test artifact. Its absence from
the isolated PostgreSQL server log was checked before the owned cluster was stopped and deleted.
Only sanitized aggregate evidence remains in ignored `_logs/phase2e-g4-results.json`.

Exact cutoff tests seed at transaction cutoff and ±1 microsecond via the owner fixture while
invoking the unchanged function as the real maintenance LOGIN. UTC/timezone cases, ordered
batch1000, concurrent workers, locked rows and accurate remaining state pass. Runtime SET ROLE
and forged GUCs do not authorize purge/append. Table, column and append EXECUTE overlap grants
are rejected. No new table access is granted to the capability.

Real subprocess CLI tests prove max-batches exit2 with committed counts, subsequent draining,
no-op, locked backlog, runtime denial and event-failure rollback. A deliberate second-batch audit
failure leaves only the first acknowledged batch committed, reported with exit1. Generated prune
events record the exact affected count and no target identifiers or arbitrary payload.

One old security guard initially matched the substring BYPASSRLS in the safe catalog field
rolbypassrls. It now ignores quoted ACL labels and checks whole SQL command tokens, retaining
prohibition of BYPASSRLS/ROW_SECURITY/SET_CONFIG/dynamic EXECUTE. All292 related tests passed
again after that correction; this was a guard false positive, not a changed RLS policy.

CI changes only provision the disposable G4 test identity inside the existing database bootstrap.
No new static credential is committed. The CI helper uses a random value and a transient runner
GITHUB_ENV file; it disables statement/duration/sample logging for the password setup connection
and prints only fixed status. GitHub CI itself was not run in this group. Scanners, broader CI
hardening, production maintenance credentials and deployment remain outside G4.

No development/production purge, scheduler, cron, job deployment, SIEM, Business Modules or Phase3.
No Authentication/RBAC/UI Settings/RLS behavior change; no frontend, Design System, dependency,
BRD/SRS or owner-report commits. Full Backend/Frontend/Playwright were not rerun in G4: the404
selected proofs cover this group and its related database security regressions. Earlier full-suite
counts remain historical evidence at their respective SHAs.

**G4 has no blocker and is operationally verified in the isolated local environment.** This does
not assert a deployed production retention SLA or backup policy. G5 has not started.
