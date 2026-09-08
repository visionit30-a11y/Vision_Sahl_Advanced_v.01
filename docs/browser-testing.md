# Browser integration tests

## Local development and browser test ports

| Purpose                  | Address                 | Owner                              |
| ------------------------ | ----------------------- | ---------------------------------- |
| Official local frontend  | `http://localhost:5173` | Existing local development process |
| Official local FastAPI   | `http://127.0.0.1:8010` | Existing Sahl application process  |
| Playwright frontend only | `http://localhost:5187` | Playwright-managed Vite process    |

The browser test port 5187 is explicitly approved for tests only. `vite.config.ts` retains the official local port 5173. There is no random port selection or fallback to 8000. An occupied 5187 causes a clear failure; Playwright never reuses an existing frontend process or terminates an unrelated process. The existing frontend process on 5173 is not touched.

## Real application requirement

From `apps/web`, `npm run test:browser` selects `real-backend.spec.ts`. Its frontend proxies `/auth`, `/ui-settings`, and `/health` to the existing real FastAPI application at `127.0.0.1:8010`. The command does not launch `security-server.mjs` or any mock API.

Before Vite starts, `real-backend-preflight.mjs` verifies both loopback bindings for port 5187, identifies the healthy Sahl application, checks the real PostgreSQL health endpoint, and checks the required auth/UI methods in its OpenAPI contract. Missing routes stop execution before any browser flow can be described as verified. Response bodies and credentials are never logged by this check.

The FastAPI test process needs these settings in its environment:

- `APP_ENV=test` (the same explicit HTTP-origin option is also valid in development).
- `AUTH_LOCAL_HTTP_ORIGIN=http://localhost:5187`, the only approved local HTTP origin. It is disabled by default and rejected in staging/production. The official frontend configuration on 5173 does not change.
- `REDIS_ENABLED=false`.
- `DATABASE_URL` for the existing non-owner `sahl_app` role and `MIGRATION_DATABASE_URL` for test fixture setup under `sahl_migrator`.
- A fresh `AUTH_HMAC_KEY` containing at least 32 bytes, held in the test process environment only, without printing or writing it to a file.

The database must be migrated to the current head before the API starts. The browser fixture provisions synthetic identities and sessions through the existing Python service boundary and PostgreSQL; it does not add a public fixture-session endpoint. Fixture credentials and cookies stay in process memory. No persisted Playwright storage state, screenshots, video, or traces are collected.

## HTTP contracts and acceptance

The current AuthClient requires real `GET /auth/csrf`, `GET /auth/me`, `GET /auth/memberships`, `POST /auth/tenant/switch`, and `POST /auth/logout` handlers. The earlier blocker was missing production HTTP handlers, not an unregistered existing router; the fixture server had supplied those responses. Their implementation uses the Phase 2B services and trusted context boundary, without a parallel authentication system or route aliases.

The real browser suite must prove refresh, effective settings, user/tenant inheritance, tenant switching, bearer/CSRF rotation, stale tabs, 401/403/409, and absence of secrets/settings persistence in browser storage. Health/OpenAPI readiness is only a prerequisite and never a substitute for those scenarios. The older `auth-security.spec.ts` and `ui-settings.spec.ts` depend on a fixture-only session route and are not selected as real application proof.

## Respecting the real CSRF throttle

The browser suite uses one worker and keeps the production policy of 30 CSRF bootstraps per IP per minute. It starts in the next PostgreSQL-aligned minute plus a one-second margin, so an earlier local run cannot consume the new suite's starting budget. It counts actual browser `GET /auth/csrf` requests and reserves at most 20 per scenario with a two-request clock margin; when the current minute cannot accommodate that budget, the next scenario waits for the next minute.

The pacing fixture has a 90-second timeout to accommodate the bounded wait. A scenario issuing more than 20 bootstraps fails as a possible bootstrap loop. Requests are not retried on 429, tests are not skipped, and no database counter, backend quota, or HMAC identity is changed to bypass throttling. This deliberate pacing may add several minutes to the real browser gate.

## Windows test-backend startup

Psycopg's asynchronous connections need the Selector event loop on Windows. In the installed Uvicorn/Python combination, a direct no-reload launch can select Proactor and make `/health/db` fail even when PostgreSQL is reachable. Pass the loop factory explicitly for this local test launch; Linux CI uses its normal event loop.

From `apps/api`, use a dedicated PowerShell terminal with the existing database connection environment available. The command fails if 8010 is occupied and does not stop that process. Coordinate any replacement of an existing Sahl process separately after verifying its ownership.

```powershell
if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8010 is occupied. No process was stopped; verify ownership before arranging a replacement.'
}
$browserPreviousEnvironment = @{}
foreach ($browserVariable in 'APP_ENV', 'AUTH_LOCAL_HTTP_ORIGIN', 'AUTH_HMAC_KEY', 'REDIS_ENABLED') {
    $browserPreviousEnvironment[$browserVariable] = [Environment]::GetEnvironmentVariable($browserVariable, 'Process')
}
try {
    $env:APP_ENV = 'test'
    $env:AUTH_LOCAL_HTTP_ORIGIN = 'http://localhost:5187'
    $env:REDIS_ENABLED = 'false'
    $env:AUTH_HMAC_KEY = (& '.\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_hex(32))')
    if ($LASTEXITCODE -ne 0) { throw 'Ephemeral test key generation failed.' }
    & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --loop asyncio:SelectorEventLoop --no-access-log
} finally {
    foreach ($browserVariable in $browserPreviousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($browserVariable, $browserPreviousEnvironment[$browserVariable], 'Process')
    }
    Remove-Variable browserPreviousEnvironment
}
```

The generated HMAC value is captured directly in memory, never displayed or written to a file. Run Playwright from `apps/web` in another terminal using the existing database configuration; the browser does not receive the HMAC key. The server command neither changes nor starts port 5173.

## Blocking CI gate

The web job provisions PostgreSQL 17 on 5433, creates the same separate migration/application roles as the backend job, installs Python dependencies from `uv.lock`, and upgrades to the current migration head. It starts the actual `app.main:app` through Uvicorn on 8010, waits for PostgreSQL health, then runs the same Playwright command on 5187.

The CI HMAC key is freshly generated inside the browser step and inherited only by its child processes; it is never written to `GITHUB_ENV`, logs, fixture files, or artifacts. The step traps exit/interruption and terminates only the exact FastAPI child PID it started. A final database cleanup/RLS guard runs even after a browser failure. There is no skip, fixture-server fallback, or `continue-on-error`.
