import type { UiPermissions } from './UiPermissions';

/**
 * A development and preview stub. It grants both permissions because there is
 * no user identity yet.
 *
 * THIS IS NOT A SECURITY CONTROL. It is the seam that keeps role checks out of
 * components; the real answer arrives with RBAC in Phase 2 by replacing this
 * implementation, and nothing that depends on it needs to change.
 */
export const previewUiPermissions: UiPermissions = {
  canManagePlatformUi: () => true,
  canManageTenantUi: () => true,
};
