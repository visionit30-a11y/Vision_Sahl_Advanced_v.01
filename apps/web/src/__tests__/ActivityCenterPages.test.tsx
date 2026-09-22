import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { activityCenterClient } from '../activity-center/client';
import i18n from '../i18n';
import { NotificationPreferencesPage } from '../pages/NotificationPreferencesPage';
import { NotificationsPage } from '../pages/NotificationsPage';
import { TasksPage } from '../pages/TasksPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../activity-center/client', () => ({
  activityCenterClient: {
    notifications: vi.fn(),
    summary: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    tasks: vi.fn(),
    preferences: vi.fn(),
    updatePreferences: vi.fn(),
    dashboard: vi.fn(),
  },
}));

const preferences = {
  approval_requested: true,
  request_approved: true,
  request_rejected: true,
  request_returned: true,
  overdue_tasks: true,
  version: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(activityCenterClient.notifications).mockResolvedValue([]);
  vi.mocked(activityCenterClient.tasks).mockResolvedValue([]);
  vi.mocked(activityCenterClient.preferences).mockResolvedValue(preferences);
  vi.mocked(activityCenterClient.updatePreferences).mockResolvedValue({
    ...preferences,
    approval_requested: false,
    version: 2,
  });
});

describe('activity center pages', () => {
  it('shows the real empty notification state and can mark all read', async () => {
    vi.mocked(activityCenterClient.markAllRead).mockResolvedValue({ marked_count: 0 });
    renderWithProviders(<NotificationsPage />);
    expect(await screen.findByText(i18n.t('activityCenter:notifications.empty'))).toBeVisible();
    fireEvent.click(screen.getByText(i18n.t('activityCenter:actions.markAllRead')));
    await waitFor(() => expect(activityCenterClient.markAllRead).toHaveBeenCalledOnce());
  });

  it('passes selected task filters to the backend client', async () => {
    renderWithProviders(<TasksPage />);
    await screen.findByText(i18n.t('activityCenter:tasks.empty'));
    fireEvent.change(screen.getByLabelText(i18n.t('activityCenter:tasks.state')), {
      target: { value: 'overdue' },
    });
    fireEvent.click(screen.getByText(i18n.t('activityCenter:actions.filter')));
    await waitFor(() =>
      expect(activityCenterClient.tasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ bucket: 'overdue' }),
      ),
    );
  });

  it('uses optimistic versions when saving preferences', async () => {
    renderWithProviders(<NotificationPreferencesPage />);
    const checkbox = await screen.findByLabelText(
      i18n.t('activityCenter:preferences.fields.approval_requested'),
    );
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(i18n.t('activityCenter:actions.save')));
    await waitFor(() =>
      expect(activityCenterClient.updatePreferences).toHaveBeenCalledWith(
        expect.objectContaining({ approval_requested: false, version: 1 }),
      ),
    );
  });
});
