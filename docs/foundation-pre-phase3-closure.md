# Foundation closure before Phase 3A

Status: local verification complete. GitHub promotion is gated separately by required checks on the source, PRs and both merge commits. No Phase 3A implementation is included.

## Login contract

GET /auth/preauth issues the existing PostgreSQL pre-auth state and synchronizer token after exact Origin and CSRF-bootstrap throttling checks. POST /auth/login accepts email/password only; consumes the pre-auth cookie/token once under a row lock, then calls PasswordAuthenticationService. Argon2id runs outside DB transactions. Existing username/IP/combined throttling applies. Missing users and wrong passwords receive the same 401. Success issues the existing Secure/HttpOnly/SameSite=Lax/Path=/ host cookie and session CSRF header. No bearer response body, browser persistence, registration or delivery paths.

The /login screen uses existing TextField/Button/Card and shared AuthClient. Membership selection is explicit; no first-membership fallback. The new browser fixture creates password credentials but never creates a session for the login proof.

## Local origins

Official development: localhost:5173 -> 127.0.0.1:8010, explicitly APP_ENV=development and AUTH_LOCAL_HTTP_ORIGIN=http://localhost:5173 in the local runner. Browser suite: localhost:5187 only, with its existing explicit exception. Staging/production reject both HTTP exceptions. No wildcard or port fallback. Never stop a pre-existing process on 5173 to run verification. SAHL_VERIFY_LOCAL_DEV=1 selects a proof against an already running frontend; verify its process belongs to this repository first. The proof does not start/replace/stop that server.

## Three index decisions

| Referencing key | Decision and concrete reason |
| --- | --- |
| app.user_ui_settings(user_id) | Add ix_user_ui_settings_user_id. Existing (tenant_id,user_id) primary key does not provide a user-leading lookup for the actual users ON DELETE CASCADE FK. |
| auth.membership_roles(tenant_id,role_id) | Add ix_membership_roles_tenant_role. Existing (tenant_id,membership_id,role_id) PK does not lead on the referenced role pair; actual role ON DELETE CASCADE checks and role assignment operations need this lookup. |
| auth.sessions(selected_membership_id,user_id) | Add ix_sessions_selected_membership_user. Existing user-active index only narrows by user; the actual membership composite RESTRICT FK searches the exact pair. |

Migration 0017 adds only these three B-tree indexes, with corresponding metadata. Downgrade removes only them. No workload speedup or load benchmark claimed; no RLS/grant changes.

## Retired browser tests

The two fixture-server specs were removed after mapping all eight scenarios to the real FastAPI/PostgreSQL suite:

- Cookie/storage -> real login and safety fixture; raw Set-Cookie attribute proof.
- CSRF/Origin -> real CSRF Origin and foreign membership gates.
- Rotation/stale tabs/forged header -> real rotation refreshes tabs.
- Logout -> real 409 blocks stale writes and logout.
- User inheritance/refresh -> real patches survive refresh and deletion.
- Tenant switching across tabs -> real rotation refreshes tabs.
- 409/401 -> real 409 blocks stale writes and logout.
- 403/no preview/storage -> real 403 disables tenant writes and safety fixture.

All approved browser tests live in real-backend.spec.ts and are selected by Playwright. Test fixture servers are not a production proof. Local results: Backend 1002 passed; Frontend 226 passed / 29 files; selected Chromium suite 8/8 passed. The separate real login journey also passed on the verified project-owned frontend at 5173, against FastAPI 8010 and isolated PostgreSQL 17. Ruff/Mypy/ESLint/TypeScript/Prettier/build, Alembic check and full migration round-trip, RLS/ownership/catalog/cleanup passed. Gitleaks source/history and approved text artifacts passed with zero findings; pip-audit (50 project + 1 build + 28 scanner entries) and npm audit (350 nodes) passed with unchanged lockfiles. No security SKIP/XFAIL or continue-on-error. GitHub run/PR evidence is attached to the protected promotion PRs; the annotated baseline must only be created after the main merge commit CI succeeds.


Required checks were read back from GitHub for both main/develop: API, Web, No committed secrets, Python dependency audit, npm dependency audit; strict=true, GitHub Actions app_id=15368, enforce_admins=true. No weakening of checks is permitted for promotion.

Commit plan executed: reviewed FK indexes; explicit development Origin; real login and browser journey; retire obsolete browser specs and record verification. The two owner reports remain untracked and excluded. GitHub merges use merge commits only; preserve feature/develop branches and fast-forward develop after the main baseline passes.
