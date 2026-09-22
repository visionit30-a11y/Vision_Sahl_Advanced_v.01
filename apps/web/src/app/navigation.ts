import type { NavSection } from '../design-system';
import { FRONTEND_PERMISSIONS } from './permission-state';

/**
 * Only routes that actually exist appear here. A module joins the navigation
 * when its own phase delivers a real screen.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    id: 'workspace',
    labelKey: 'sections.workspace',
    items: [
      { id: 'home', labelKey: 'items.home', icon: 'home', to: '/', end: true },
      {
        id: 'design-system',
        labelKey: 'items.designSystem',
        icon: 'layers',
        to: '/design-system',
        requiredPermission: FRONTEND_PERMISSIONS.manageOwnUiSettings,
      },
    ],
  },
  {
    id: 'workflow',
    labelKey: 'sections.workflow',
    items: [
      {
        id: 'workflow-requests',
        labelKey: 'items.workflowRequests',
        icon: 'inbox',
        to: '/workflows/requests',
        requiredPermission: FRONTEND_PERMISSIONS.readWorkflowRequests,
      },
      {
        id: 'workflow-approvals',
        labelKey: 'items.workflowApprovals',
        icon: 'check',
        to: '/workflows/approvals',
        requiredPermission: FRONTEND_PERMISSIONS.decideWorkflowApprovals,
      },
      {
        id: 'tasks',
        labelKey: 'items.tasks',
        icon: 'check',
        to: '/tasks',
        requiredPermission: FRONTEND_PERMISSIONS.decideWorkflowApprovals,
      },
      {
        id: 'notifications',
        labelKey: 'items.notifications',
        icon: 'bell',
        to: '/notifications',
        requiredPermission: FRONTEND_PERMISSIONS.readWorkflowRequests,
      },
      {
        id: 'notification-preferences',
        labelKey: 'items.notificationPreferences',
        icon: 'layers',
        to: '/settings/notifications',
        requiredPermission: FRONTEND_PERMISSIONS.manageOwnUiSettings,
      },
    ],
  },
  {
    id: 'tenant-administration',
    labelKey: 'sections.tenantAdministration',
    items: [
      {
        id: 'tenant-users',
        labelKey: 'items.tenantUsers',
        icon: 'layers',
        to: '/settings/users',
        requiredPermission: FRONTEND_PERMISSIONS.readTenantUsers,
      },
      {
        id: 'change-password',
        labelKey: 'items.changePassword',
        icon: 'check',
        to: '/settings/password',
      },
    ],
  },
];
