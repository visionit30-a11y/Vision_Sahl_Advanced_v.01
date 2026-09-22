import { authClient } from '../auth/client';

export type NotificationKind =
  | 'request_submitted'
  | 'approval_requested'
  | 'request_returned'
  | 'request_rejected'
  | 'request_approved'
  | 'task_overdue';

export interface NotificationRecord {
  id: string;
  request_id: string;
  kind: NotificationKind;
  title_snapshot: string;
  read_at: string | null;
  created_at: string;
}

export interface TaskRecord {
  id: string;
  request_id: string;
  title: string;
  request_type: string;
  status: string;
  bucket: 'open' | 'completed' | 'overdue';
  version: number;
  created_at: string;
  due_at: string;
  decided_at: string | null;
}

export interface NotificationPreferences {
  approval_requested: boolean;
  request_approved: boolean;
  request_rejected: boolean;
  request_returned: boolean;
  overdue_tasks: boolean;
  version: number;
}

export interface DashboardSummary {
  unread_notifications: number;
  pending_tasks: number;
  overdue_tasks: number;
  recent_activity: Array<{
    request_id: string;
    title: string;
    event_type: string;
    actor_kind: string;
    from_status: string | null;
    to_status: string;
    created_at: string;
  }>;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await authClient.request(path, init)).json()) as T;
}

export const activityCenterClient = {
  notifications: () => json<NotificationRecord[]>('/activity-center/notifications'),
  summary: () => json<{ unread_count: number }>('/activity-center/notifications/summary'),
  markRead: (id: string) =>
    json<NotificationRecord>(`/activity-center/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () =>
    json<{ marked_count: number }>('/activity-center/notifications/read-all', { method: 'POST' }),
  tasks: (filters: {
    bucket?: string;
    requestType?: string;
    createdFrom?: string;
    createdTo?: string;
  }) => {
    const query = new URLSearchParams();
    if (filters.bucket) query.set('bucket', filters.bucket);
    if (filters.requestType) query.set('request_type', filters.requestType);
    if (filters.createdFrom) query.set('created_from', new Date(filters.createdFrom).toISOString());
    if (filters.createdTo) query.set('created_to', new Date(filters.createdTo).toISOString());
    return json<TaskRecord[]>(`/activity-center/tasks?${query.toString()}`);
  },
  preferences: () => json<NotificationPreferences>('/activity-center/preferences'),
  updatePreferences: (value: NotificationPreferences) =>
    json<NotificationPreferences>('/activity-center/preferences', {
      method: 'PUT',
      body: JSON.stringify({
        approval_requested: value.approval_requested,
        request_approved: value.request_approved,
        request_rejected: value.request_rejected,
        request_returned: value.request_returned,
        overdue_tasks: value.overdue_tasks,
        expected_version: value.version,
      }),
    }),
  dashboard: () => json<DashboardSummary>('/activity-center/dashboard'),
};
