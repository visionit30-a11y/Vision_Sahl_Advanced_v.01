# Phase 2D — Exit Criteria and G6 Evidence

**Scope:** Backend-persisted UI settings and permission-aware frontend integration.
**Review date:** 2026-09-08.
**Reviewed implementation HEAD:** `d09f2e339e15b711c4fdf257112f253d4d87980b`.
**Baseline/develop:** `e6072195079158d12dcb0ff95b0cd5343a3ba50e` (`phase-2c-baseline`).
**Migration head:** `0013_auth_http_projections`.

The owner accepted G5 as operationally verified: Backend **490 passed**, Frontend
**225 passed / 29 files**, Chromium **7/7 passed**, using
`localhost:5187 → FastAPI 127.0.0.1:8010 → PostgreSQL`.
Fresh G6 gates below independently reproduce the accepted counts. Local exit criteria: **19/19 PASS**. GitHub evidence belongs to the exact pushed source HEAD and is recorded in the PR.

## Mandatory exit criteria

All implementation criteria were checked against the fresh complete G6 suites. Static scope checks refer to the reviewed branch diff; they do not replace behavioral tests.

| # | Required outcome | Evidence and boundary | G6 status |
| --- | --- | --- | --- |
| 1 | Backend-persisted UI settings are the source of truth | `httpUiSettingsSource` loads effective and protected layers through the existing AuthClient; provider applies writes only after server confirmation. Browser: `real backend wins over legacy storage and network failure stays visible`. | PASS |
| 2 | User → Tenant → Platform → Built-in precedence | `test_effective_resolution_precedence_partial_patches_and_origins` covers all four layers and partial patches. Browser proves persisted User/Tenant inheritance. Platform remains a read-only layer. | PASS |
| 3 | Correct origin for every setting | The resolution contract returns each key's origin. Service precedence test and browser `real patches survive refresh and deletion restores inheritance origins` assert the origin map. | PASS |
| 4 | localStorage is not the settings source of truth | `browserUiSettingsSource` was deleted; settings runtime storage is forbidden by `uiBoundaries.test.ts`. Browser injects legacy storage and proves Backend wins. Unrelated language preference is outside the settings authority contract. | PASS |
| 5 | Preview authority removed | `previewUiPermissions` and the browser `UiPermissions` authority adapter were deleted. Protected-layer 403 responses disable controls; backend AuthorizationService remains authoritative. | PASS |
| 6 | No preview-tenant authority | `previewTenant.ts` was deleted; the runtime guard forbids `PREVIEW_TENANT_ID` and `preview-tenant`. HTTP contracts accept no tenant/user authority selector. | PASS |
| 7 | No Platform write path | Service and repository expose Platform read only. `test_platform_write_path_is_not_available` and HTTP route guards reject a write surface. Migration 0012 grants runtime SELECT only on the Platform table; the typed permission is reserved. | PASS |
| 8 | HTTP User/Tenant persistence works | Seven real `/ui-settings` operations implement effective read and User/Tenant GET/PUT/DELETE. HTTP tests cover CRUD; browser proves persistence, refresh and deletion inheritance against real PostgreSQL. | PASS |
| 9 | Optimistic versioning works | Expected versions constrain atomic writes. PostgreSQL create/update and delete/update races have one winner; `test_unique_user_scope_and_optimistic_version_conflict` and browser 409 checks cover conflicts. | PASS |
| 10 | 401/403/409 contracts are correct | `test_missing_session_and_missing_permission_are_denied`, HTTP validation/conflict tests and real-browser unauthenticated, permission-denial and stale-write scenarios. Errors remain sanitized and no-store. | PASS |
| 11 | Tenant switch refetches settings | Browser `real rotation refreshes tabs and rejects old bearer CSRF and membership`; AuthClient invalidation causes the provider to fetch the server state for the selected membership. | PASS |
| 12 | Session rotation leaves no stale state | Provider `discards an old tenant response arriving after rotation`; browser proves new tenant state and immediate rejection of old bearer/CSRF. | PASS |
| 13 | Stale tabs are handled | Real-browser rotation test and `test_real_ui_settings_dependency_enforces_csrf_origin_and_stale_tab_before_write`; mismatched expected membership is rejected with 409 and `tenant_context_changed`. | PASS |
| 14 | Real auth HTTP routes exist | `test_auth_session_routes_are_registered_on_real_application` and browser OpenAPI proof cover `/auth/me`, `/auth/memberships`, `/auth/csrf`, `/auth/tenant/switch` and `/auth/logout`. Existing Phase 2B services back the handlers. | PASS |
| 15 | Playwright uses real FastAPI/PostgreSQL | Blocking preflight checks Sahl health, database health and the real OpenAPI operations. `real-backend.spec.ts` is the configured suite; no security-server process is launched. Fixture setup uses real PostgreSQL and existing session services, with no fixture endpoint added to FastAPI. | PASS |
| 16 | RLS, ownership and cleanup guards pass | SQL/ORM cross-tenant tests, `test_rls_catalog`, UI ownership/grant guards and auth projection guards. New tenant tables add ENABLE + FORCE RLS and USING + WITH CHECK; migration 0013 adds no direct table grants. Fresh cleanup and committed migration round-trip gates also passed. | PASS |
| 17 | Design System remains functionally compatible | No changes to Design System component sources, theme/preset registries, `resolveUiSettings` or `applyUiSettings` in the branch diff. The settings controls intentionally switch from preview Platform editing to server-backed User/Tenant editing. Full frontend regression suite is required. | PASS |
| 18 | No Phase 2E implementation | Changed application paths are confined to UI settings, the approved auth HTTP completion and their security/configuration boundaries. No Phase 2E subsystem or schema was added. | PASS — scope diff |
| 19 | No Business Modules | New domain/application paths are `ui_settings` and the approved auth HTTP adapter only. New tables are settings tables; migration 0013 contains only the two approved auth projections. | PASS — scope diff |

## Scope and history checks

- Tracked tree was clean at review; only the two owner reports were untracked:
  `docs/TECHNICAL_PROJECT_HANDOVER_REPORT.md` and `تقرير المشروع حتى 07-09-2026/`.
  They must remain outside commits and the PR.
- No tracked BRD/SRS path changed against develop.
- Existing migrations 0001–0011 are unchanged. The branch adds migrations 0012 and 0013.
- No change to the existing TenantContext/tenancy implementation or the centralized
  AuthorizationService; no alternative authorization decision service was added.
- Tenant settings and User settings are tenant-owned. Platform settings are global
  and runtime read-only; tenant roles do not gain Platform authority.
- The approved session-bound SECURITY DEFINER functions use fixed
  `search_path=pg_catalog`, owner `sahl_migrator`, no PUBLIC EXECUTE, and exact
  signature EXECUTE grants to `sahl_app`. They do not create TenantContext or alter
  `app.current_tenant_id()`, FORCE RLS or transaction-local context.
- Official local ports remain frontend 5173 and backend 8010. Frontend 5187 is
  dedicated to browser tests with strict port binding and no automatic fallback.

## Fresh G6 gates

Fresh local acceptance completed on 2026-09-08. Logs remain ignored under `_logs/phase2d-g6-*`; no reports or credentials are staged.

| Gate | Fresh G6 result |
| --- | --- |
| Backend full suite with strict security gates | PASS — 490 passed (40.26s), no skipped security proof |
| Frontend full suite | PASS — 225 passed / 29 files |
| Real Playwright Chromium gate | PASS — 7/7 (3.2m), 5187 → actual FastAPI8010 → PostgreSQL |
| Ruff | PASS |
| Mypy | PASS — 118 source files |
| ESLint | PASS |
| TypeScript | PASS |
| Prettier | PASS |
| Production build | PASS |
| Alembic check | PASS — no new upgrade operations |
| Migration round-trip | PASS — committed head → base → head on disposable PostgreSQL17 |
| PostgreSQL/RLS/catalog/ownership/grants guards | PASS — full backend suite; 6 production tenant tables verified |
| No committed secrets | PASS — tracked environment/credential scan; both reports excluded |
| Cleanup guards | PASS — isolated backend database and real browser database |
| Tracked working tree clean before push; reports excluded | PASS — G6 documentation committed separately; both reports remain untracked |

The migration gate used an isolated native PostgreSQL17 cluster on fixed loopback5434,
with the same migration/application roles and role setup as CI. Every upgrade and
downgrade committed normally; base and final head were observed independently.
The disposable cluster was stopped and its verified temporary data directory removed.
The development database on5433 retained its existing security events and settings.
Browser testing kept its approved path through FastAPI8010 and frontend5187; official
frontend5173 and the unrelated8000 service were not stopped or reassigned.

## Remote review gate

The pushed source HEAD must pass GitHub CI before the PR is created. The PR records
the exact source SHA, source workflow run, job results and local evidence from this
document. PR-triggered checks are tracked separately. Local results do not replace
remote CI, and CI on a future merge commit requires separate verification.

G6 authorizes the current branch push and a PR to develop only. No merge, baseline
tag, Phase2E, Business Modules or Platform write implementation is authorized here.
