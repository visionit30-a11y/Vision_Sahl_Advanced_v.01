# Phase 3C — Notifications, Tasks & Activity Center

Phase 3C extends the shared Phase 3B workflow without creating a business module. All persisted records remain tenant scoped and use the trusted session, `TenantContext`, centralized `AuthorizationService`, `tenant_transaction()`, and PostgreSQL `FORCE RLS` path.

## Delivered contracts

- `app.notifications` stores in-app workflow notifications for one recipient membership. It stores a safe title snapshot and resource identifier, never a request body, credential, token, or technical exception.
- `app.notification_preferences` stores per-membership, per-tenant in-app preferences with optimistic versioning. Security and mandatory platform notices are outside these switches and remain enabled.
- `app.workflow_approval_tasks.due_at` makes the existing approval work item the source of truth for open, completed, and overdue task views. A task closes atomically with its workflow decision.
- `app.workflow_events` remains the append-only timeline. The API exposes only the lifecycle event, safe actor kind, state transition, optional decision note, and time.
- Overdue notifications are materialized idempotently when the assignee opens the task center. This phase adds no scheduler or external delivery channel.

## HTTP API

All responses are `Cache-Control: no-store`; tenant and recipient selectors are derived from the trusted session.

- `GET /activity-center/notifications`
- `GET /activity-center/notifications/summary`
- `POST /activity-center/notifications/{notification_id}/read`
- `POST /activity-center/notifications/read-all`
- `GET /activity-center/tasks?bucket=&request_type=&created_from=&created_to=`
- `GET /activity-center/preferences`
- `PUT /activity-center/preferences`
- `GET /activity-center/dashboard`

The existing `GET /workflows/requests/{request_id}/history` is the request activity timeline. The UI links notifications and tasks back to the related workflow request.

## Authorization and isolation

- Notification and dashboard reads reuse the typed `tenant.workflow_requests.read` grant.
- Task reads reuse `tenant.workflow_approvals.decide` and additionally restrict every query to the current membership.
- Preference writes reuse `tenant.user_ui_settings.manage_self` and require an expected version.
- RLS protects every new table by `tenant_id`; service predicates enforce recipient and assignee ownership inside that tenant.
- Cross-tenant and foreign-recipient identifiers return no resource. Self approval remains blocked by Phase 3B.

## User experience

The application shell adds an unread bell, notifications page, My Tasks page, notification preferences, dashboard indicators, and localized request timelines. Arabic remains the default and every new screen uses the existing responsive design system with full RTL/LTR support.

## Verification

Migration `0019_activity_center` is reversible to `0018_workflow_approvals`. PostgreSQL tests cover the lifecycle, preference conflicts, task closure, recipient isolation, RLS, ownership, and grants. Browser coverage uses the real login, FastAPI, PostgreSQL, workflow request, notification, task, decision, result notification, and activity timeline paths. No email, SMS, WhatsApp, business module, or external integration is included.
