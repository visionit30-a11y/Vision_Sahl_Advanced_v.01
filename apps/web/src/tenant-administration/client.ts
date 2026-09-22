import { authClient } from '../auth/client';

export interface TenantUser {
  membership_id: string;
  user_id: string;
  email: string;
  user_status: string;
  membership_status: string;
  membership_version: number;
  joined_at: string | null;
  left_at: string | null;
  role_ids: string[];
  role_keys: string[];
  role_titles: string[];
}

export interface TenantRole {
  role_id: string;
  role_key: string;
  display_name: string;
  status: string;
  kind: 'custom' | 'tenant_admin';
  version: number;
  permissions: string[];
}

export interface AccessEvent {
  id: string;
  event_type: string;
  actor_membership_id: string | null;
  target_membership_id: string;
  role_id: string | null;
  created_at: string;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await authClient.request(path, init)).json()) as T;
}

export const tenantAdministrationClient = {
  users: () => json<TenantUser[]>('/tenant-admin/users'),
  roles: () => json<TenantRole[]>('/tenant-admin/roles'),
  events: () => json<AccessEvent[]>('/tenant-admin/access-events'),
  invite: (email: string) =>
    json<{ membership_id: string }>('/tenant-admin/users/invitations', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  setStatus: (membershipId: string, status: 'active' | 'suspended', expectedVersion: number) =>
    json<{ status: string; version: number }>(`/tenant-admin/memberships/${membershipId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, expected_version: expectedVersion }),
    }),
  assignRole: (membershipId: string, roleId: string) =>
    json<{ changed: boolean }>(`/auth/memberships/${membershipId}/roles/${roleId}`, {
      method: 'PUT',
    }),
  removeRole: (membershipId: string, roleId: string) =>
    json<{ changed: boolean }>(`/auth/memberships/${membershipId}/roles/${roleId}`, {
      method: 'DELETE',
    }),
};
