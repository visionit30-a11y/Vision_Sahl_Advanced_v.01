/* eslint-disable react-refresh/only-export-components */

import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from 'react';

import { useUiCustomization } from '../ui-customization';
import type { SettingsStatus } from '../ui-customization/UiCustomizationContext';
import type { WorkflowPermissionLoader } from '../workflow/client';

/**
 * Frontend identifiers mirror the typed backend catalogue. They only control
 * presentation; every protected operation is still authorized by FastAPI.
 */
export const FRONTEND_PERMISSIONS = {
  manageOwnUiSettings: 'tenant.user_ui_settings.manage_self',
  manageTenantUiSettings: 'tenant.ui_settings.manage',
  createWorkflowRequests: 'tenant.workflow_requests.create',
  readWorkflowRequests: 'tenant.workflow_requests.read',
  decideWorkflowApprovals: 'tenant.workflow_approvals.decide',
} as const;

export type FrontendPermission = (typeof FRONTEND_PERMISSIONS)[keyof typeof FRONTEND_PERMISSIONS];

export type PermissionSnapshotStatus = 'loading' | 'ready' | 'forbidden' | 'unavailable';

export interface FrontendPermissionSnapshot {
  status: PermissionSnapshotStatus;
  loading: boolean;
  allows(permission?: FrontendPermission | string): boolean;
}

const DEFAULT_SNAPSHOT: FrontendPermissionSnapshot = {
  status: 'loading',
  loading: true,
  allows: (permission) => permission === undefined,
};

const FrontendPermissionContext = createContext<FrontendPermissionSnapshot>(DEFAULT_SNAPSHOT);

function snapshotStatus(status: SettingsStatus): PermissionSnapshotStatus {
  if (status === 'loading' || status === 'saving') return 'loading';
  if (status === 'ready') return 'ready';
  if (status === 'forbidden') return 'forbidden';
  return 'unavailable';
}

export function FrontendPermissionProvider({
  children,
  loadWorkflowPermissions,
}: {
  children: ReactNode;
  loadWorkflowPermissions?: WorkflowPermissionLoader;
}) {
  const customization = useUiCustomization();
  const status = snapshotStatus(customization.status);
  const lastProven = useRef<Set<FrontendPermission>>(new Set());
  const [workflowPermissions, setWorkflowPermissions] = useState<Set<FrontendPermission>>(
    new Set(),
  );
  const [workflowLoading, setWorkflowLoading] = useState(Boolean(loadWorkflowPermissions));

  useEffect(() => {
    let active = true;
    if (!loadWorkflowPermissions) return;
    setWorkflowLoading(true);
    void loadWorkflowPermissions().then(
      (values) => {
        if (!active) return;
        const known = new Set(Object.values(FRONTEND_PERMISSIONS));
        setWorkflowPermissions(
          new Set(
            values.filter((value) =>
              known.has(value as FrontendPermission),
            ) as FrontendPermission[],
          ),
        );
        setWorkflowLoading(false);
      },
      () => {
        if (!active) return;
        setWorkflowPermissions(new Set());
        setWorkflowLoading(false);
      },
    );
    return () => {
      active = false;
    };
  }, [loadWorkflowPermissions]);

  if (status === 'ready') {
    const granted = new Set<FrontendPermission>();
    if (customization.canManage('user')) {
      granted.add(FRONTEND_PERMISSIONS.manageOwnUiSettings);
    }
    if (customization.canManage('tenant')) {
      granted.add(FRONTEND_PERMISSIONS.manageTenantUiSettings);
    }
    for (const permission of workflowPermissions) granted.add(permission);
    lastProven.current = granted;
  } else if (status === 'forbidden' || customization.status === 'unauthorized') {
    lastProven.current = new Set();
  }

  // Retained evidence only keeps presentation stable for a visible conflict
  // or network error. It never authorizes a request; server enforcement and
  // the customization write controls still fail closed.
  const granted = new Set(lastProven.current);
  const combinedStatus = status === 'ready' && workflowLoading ? 'loading' : status;
  const value: FrontendPermissionSnapshot = {
    status: combinedStatus,
    loading: combinedStatus === 'loading',
    allows: (permission) =>
      permission === undefined || granted.has(permission as FrontendPermission),
  };

  return (
    <FrontendPermissionContext.Provider value={value}>
      {children}
    </FrontendPermissionContext.Provider>
  );
}

export function usePermissionSnapshot(): FrontendPermissionSnapshot {
  return useContext(FrontendPermissionContext);
}
