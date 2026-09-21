/* eslint-disable react-refresh/only-export-components */

import { createContext, type ReactNode, useContext, useRef } from 'react';

import { useUiCustomization } from '../ui-customization';
import type { SettingsStatus } from '../ui-customization/UiCustomizationContext';

/**
 * Frontend identifiers mirror the typed backend catalogue. They only control
 * presentation; every protected operation is still authorized by FastAPI.
 */
export const FRONTEND_PERMISSIONS = {
  manageOwnUiSettings: 'tenant.user_ui_settings.manage_self',
  manageTenantUiSettings: 'tenant.ui_settings.manage',
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

export function FrontendPermissionProvider({ children }: { children: ReactNode }) {
  const customization = useUiCustomization();
  const status = snapshotStatus(customization.status);
  const lastProven = useRef<Set<FrontendPermission>>(new Set());

  if (status === 'ready') {
    const granted = new Set<FrontendPermission>();
    if (customization.canManage('user')) {
      granted.add(FRONTEND_PERMISSIONS.manageOwnUiSettings);
    }
    if (customization.canManage('tenant')) {
      granted.add(FRONTEND_PERMISSIONS.manageTenantUiSettings);
    }
    lastProven.current = granted;
  } else if (status === 'forbidden' || customization.status === 'unauthorized') {
    lastProven.current = new Set();
  }

  // Retained evidence only keeps presentation stable for a visible conflict
  // or network error. It never authorizes a request; server enforcement and
  // the customization write controls still fail closed.
  const granted = new Set(lastProven.current);
  const value: FrontendPermissionSnapshot = {
    status,
    loading: status === 'loading',
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
