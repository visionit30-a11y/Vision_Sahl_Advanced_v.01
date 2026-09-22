import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { authClient } from '../auth/client';
import i18n from '../i18n';
import { ChangePasswordPage } from '../pages/ChangePasswordPage';
import { TenantUsersPage } from '../pages/TenantUsersPage';
import { tenantAdministrationClient } from '../tenant-administration/client';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../app/auth-state', () => ({
  useAppAuth: () => ({ selectedMembershipId: 'membership-self' }),
}));

vi.mock('../app/permission-state', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../app/permission-state')>();
  return {
    ...actual,
    usePermissionSnapshot: () => ({
      status: 'ready',
      loading: false,
      allows: () => true,
    }),
  };
});

vi.mock('../tenant-administration/client', () => ({
  tenantAdministrationClient: {
    users: vi.fn(),
    roles: vi.fn(),
    events: vi.fn(),
    invite: vi.fn(),
    setStatus: vi.fn(),
    assignRole: vi.fn(),
    removeRole: vi.fn(),
  },
}));

const user = {
  membership_id: 'membership-other',
  user_id: 'user-other',
  email: 'member@example.test',
  user_status: 'active',
  membership_status: 'active',
  membership_version: 1,
  joined_at: '2026-09-20T00:00:00Z',
  left_at: null,
  role_ids: [],
  role_keys: [],
  role_titles: [],
};

const role = {
  role_id: 'role-reviewer',
  role_key: 'reviewer',
  display_name: 'Reviewer',
  status: 'active',
  kind: 'custom' as const,
  version: 1,
  permissions: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(tenantAdministrationClient.users).mockResolvedValue([user]);
  vi.mocked(tenantAdministrationClient.roles).mockResolvedValue([role]);
  vi.mocked(tenantAdministrationClient.events).mockResolvedValue([]);
  vi.mocked(tenantAdministrationClient.invite).mockResolvedValue({
    membership_id: 'membership-new',
  });
  vi.mocked(tenantAdministrationClient.setStatus).mockResolvedValue({
    status: 'suspended',
    version: 2,
  });
  vi.mocked(tenantAdministrationClient.assignRole).mockResolvedValue({ changed: true });
  vi.spyOn(authClient, 'changePassword').mockResolvedValue(undefined);
});

describe('tenant administration', () => {
  it('loads the server directory and performs typed tenant actions', async () => {
    renderWithProviders(<TenantUsersPage />);
    expect(await screen.findByText('member@example.test')).toBeVisible();

    fireEvent.change(
      screen.getByLabelText(new RegExp(i18n.t('tenantAdministration:invite.email')), {
        selector: 'input[name="email"]',
      }),
      {
        target: { value: 'invitee@example.test' },
      },
    );
    fireEvent.click(screen.getByText(i18n.t('tenantAdministration:invite.submit')));
    await waitFor(() =>
      expect(tenantAdministrationClient.invite).toHaveBeenCalledWith('invitee@example.test'),
    );

    fireEvent.click(screen.getByText(i18n.t('tenantAdministration:actions.suspend')));
    await waitFor(() =>
      expect(tenantAdministrationClient.setStatus).toHaveBeenCalledWith(
        'membership-other',
        'suspended',
        1,
      ),
    );

    fireEvent.change(screen.getByLabelText(i18n.t('tenantAdministration:roles.assign')), {
      target: { value: 'role-reviewer' },
    });
    await waitFor(() =>
      expect(tenantAdministrationClient.assignRole).toHaveBeenCalledWith(
        'membership-other',
        'role-reviewer',
      ),
    );
  });

  it('submits password changes through the established auth client', async () => {
    renderWithProviders(<ChangePasswordPage />, '/settings/password');
    fireEvent.change(
      screen.getByLabelText(new RegExp(i18n.t('tenantAdministration:password.current')), {
        selector: 'input[name="currentPassword"]',
      }),
      {
        target: { value: 'Current password value' },
      },
    );
    fireEvent.change(
      screen.getByLabelText(new RegExp(i18n.t('tenantAdministration:password.new')), {
        selector: 'input[name="newPassword"]',
      }),
      {
        target: { value: 'A stronger password value' },
      },
    );
    fireEvent.change(
      screen.getByLabelText(new RegExp(i18n.t('tenantAdministration:password.confirm')), {
        selector: 'input[name="confirmPassword"]',
      }),
      {
        target: { value: 'A stronger password value' },
      },
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: i18n.t('tenantAdministration:password.submit'),
      }),
    );
    await waitFor(() =>
      expect(authClient.changePassword).toHaveBeenCalledWith(
        'Current password value',
        'A stronger password value',
        'A stronger password value',
      ),
    );
  });
});
