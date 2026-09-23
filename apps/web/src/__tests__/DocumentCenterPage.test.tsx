import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { NAV_SECTIONS } from '../app/navigation';
import { FRONTEND_PERMISSIONS } from '../app/permission-state';
import i18n from '../i18n';
import { DocumentCenterPage } from '../pages/DocumentCenterPage';
import { renderWithProviders } from '../test/renderWithProviders';
import { workflowClient } from '../workflow/client';

const auth = vi.hoisted(() => ({ selectedMembershipId: 'member-a' }));

vi.mock('../app/auth-state', () => ({ useAppAuth: () => auth }));
vi.mock('../workflow/client', () => ({
  workflowClient: { documentCenter: vi.fn(), downloadDocument: vi.fn() },
}));

const document = {
  id: 'document-1',
  tenant_id: 'tenant-a',
  request_id: 'request-1',
  uploaded_by_membership_id: 'member-a',
  filename: 'report.pdf',
  content_type: 'application/pdf',
  byte_size: 1024,
  sha256: 'a'.repeat(64),
  created_at: '2026-09-23T00:00:00Z',
  request_title: 'Quarterly request',
  request_status: 'draft' as const,
  relation: 'requester' as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.selectedMembershipId = 'member-a';
  vi.mocked(workflowClient.documentCenter).mockResolvedValue([document]);
});

it('shows the documents route in navigation under the typed read permission', () => {
  const item = NAV_SECTIONS.flatMap((section) => section.items).find(
    (entry) => entry.to === '/documents',
  );
  expect(item?.requiredPermission).toBe(FRONTEND_PERMISSIONS.readWorkflowRequests);
});

it('renders server-owned documents and clears them when the membership changes', async () => {
  const view = renderWithProviders(<DocumentCenterPage />);
  expect(await screen.findByText('report.pdf')).toBeVisible();
  expect(screen.getByText(/Quarterly request/)).toBeVisible();

  vi.mocked(workflowClient.documentCenter).mockResolvedValue([]);
  auth.selectedMembershipId = 'member-b';
  view.rerender(<DocumentCenterPage />);
  expect(await screen.findByText(i18n.t('workflow:documents.centerEmpty'))).toBeVisible();
  expect(screen.queryByText('report.pdf')).not.toBeInTheDocument();
  expect(workflowClient.documentCenter).toHaveBeenCalledTimes(2);
});

it('keeps errors visible and retries without cached documents', async () => {
  vi.mocked(workflowClient.documentCenter).mockRejectedValueOnce(new Error('offline'));
  renderWithProviders(<DocumentCenterPage />);
  expect(await screen.findByText(i18n.t('workflow:documents.error'))).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: i18n.t('workflow:actions.retry') }));
  await waitFor(() => expect(screen.getByText('report.pdf')).toBeVisible());
});
