import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';

import { useAppAuth } from './auth-state';
import { DesignSystemPage } from '../pages/DesignSystemPage';
import { LoginPage } from '../pages/LoginPage';
import { HomePage } from '../pages/HomePage';
import { WorkflowRequestsPage } from '../pages/WorkflowRequestsPage';
import { WorkflowApprovalsPage } from '../pages/WorkflowApprovalsPage';
import { NotificationsPage } from '../pages/NotificationsPage';
import { TasksPage } from '../pages/TasksPage';
import { NotificationPreferencesPage } from '../pages/NotificationPreferencesPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { AppLayout } from './AppLayout';
import { AppProviders } from './AppProviders';
import { FRONTEND_PERMISSIONS, usePermissionSnapshot } from './permission-state';
import type { FrontendPermission } from './permission-state';
import {
  ForbiddenShellState,
  ErrorShellState,
  LoadingShellState,
  NoMembershipShellState,
  SessionExpiredShellState,
  TenantSelectionShellState,
} from './ShellStatePage';

interface ProtectedRouteProps {
  requiredPermission?: FrontendPermission;
  children: ReactNode;
}

function ProtectedRoute({ children, requiredPermission }: ProtectedRouteProps) {
  const location = useLocation();
  const auth = useAppAuth();
  const permissions = usePermissionSnapshot();

  if (auth.status === 'loading') return <LoadingShellState />;
  if (auth.status === 'unauthenticated') {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (auth.status === 'forbidden') return <ForbiddenShellState />;
  if (auth.status === 'session-expired') return <SessionExpiredShellState />;
  if (auth.status === 'no-membership') return <NoMembershipShellState />;
  if (auth.status === 'tenant-not-selected') return <TenantSelectionShellState />;
  if (auth.status === 'error') return <ErrorShellState />;
  if (requiredPermission && permissions.loading) return <LoadingShellState />;
  if (requiredPermission && permissions.status === 'unavailable') {
    // Keep the authenticated route mounted so its server-backed provider can
    // show the specific conflict/network recovery state. Write controls still
    // fail closed and every operation remains authorized by the backend.
    return <AppLayout>{children}</AppLayout>;
  }
  if (!permissions.allows(requiredPermission)) return <ForbiddenShellState />;

  return <AppLayout>{children}</AppLayout>;
}

export function App() {
  return (
    <BrowserRouter>
      <AppProviders>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <HomePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workflows/requests"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.readWorkflowRequests}>
                <WorkflowRequestsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workflows/approvals"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.decideWorkflowApprovals}>
                <WorkflowApprovalsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/design-system"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.manageOwnUiSettings}>
                <DesignSystemPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/notifications"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.readWorkflowRequests}>
                <NotificationsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tasks"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.decideWorkflowApprovals}>
                <TasksPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings/notifications"
            element={
              <ProtectedRoute requiredPermission={FRONTEND_PERMISSIONS.manageOwnUiSettings}>
                <NotificationPreferencesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="*"
            element={
              <ProtectedRoute>
                <NotFoundPage />
              </ProtectedRoute>
            }
          />
        </Routes>
      </AppProviders>
    </BrowserRouter>
  );
}
