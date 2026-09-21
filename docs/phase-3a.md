# Phase 3A — Application shell and functional UI foundation

## Delivered batch

This batch replaces the foundation/demo entry flow with an authenticated application shell. It
uses the existing Phase 2 authentication, tenant context, authorization and persisted UI-settings
contracts; it adds no business module and no frontend authorization authority.

The usable flow is:

1. `/login` submits email and password through the existing `AuthClient`.
2. The server issues the existing PostgreSQL-backed session cookie and CSRF token.
3. `/auth/me` is followed by an unconditional `/auth/memberships` read.
4. A fresh session with memberships and no selected membership displays an explicit tenant
   selector. The first tenant is never selected automatically.
5. A successful switch rotates the session and CSRF state, refreshes trusted identity, and mounts
   the tenant-scoped providers.
6. The authenticated shell renders the current user, current tenant, navigation, breadcrumbs,
   language control and logout action around the home workspace.

## Shell states

The router handles loading, unauthenticated, no membership, tenant not selected, forbidden,
expired session and recoverable connection error states explicitly. Login, logout and tenant
switch operations suppress their own cross-tab invalidation event until the operation completes;
this prevents a local refresh from racing the pre-auth/login or rotation exchange. Events from
other tabs still trigger a fresh server read.

UI settings and permission presentation are mounted only after the server has established a
selected tenant. This clears tenant-scoped state during rotation and prevents anonymous UI-settings
requests from racing login.

## Permission-aware navigation

`permission-state.tsx` contains the frontend mirror of the typed permission identifiers used by
the current screens:

- `tenant.user_ui_settings.manage_self`
- `tenant.ui_settings.manage`

The mirror consumes only authorization results already returned by the server-backed UI settings
adapter. Unknown identifiers fail closed. Navigation hiding and route presentation are usability
controls only. FastAPI `AuthorizationService`, tenant transactions and PostgreSQL RLS remain the
enforcement boundary.

If an authenticated settings page encounters a version conflict or network failure, the route
stays mounted to show its specific recovery message while all write controls fail closed. A real
403 clears the presentation permission and both hides the navigation item and denies a direct URL.

## Compatibility and verification

The shell keeps the existing AppShell and Design System components, tokens, presets, IBM Plex Sans
Arabic, Arabic RTL and English LTR behavior. The home route adds a compact current-context panel
and retains service-health visibility without introducing business data.

Unit coverage proves membership loading without automatic selection, true no-membership state,
explicit selection, session expiry and fail-closed permission presentation. The real browser gate
proves login, session cookie, explicit tenant selection, refresh, rotation, logout, permission-aware
navigation, direct-URL denial, RTL/LTR and desktop/tablet/mobile layout against real FastAPI and
PostgreSQL.

Out of scope: business modules, new permissions, role administration UI, registration, MFA,
notification delivery, Phase 3B and changes to RLS/Auth/RBAC contracts.

## Local verification

- Frontend unit tests: 31 files / 232 tests passed.
- Real Playwright browser gate: 10/10 passed against FastAPI and PostgreSQL.
- ESLint, TypeScript, Prettier and the production build passed.
- `npm audit`: zero vulnerabilities.
