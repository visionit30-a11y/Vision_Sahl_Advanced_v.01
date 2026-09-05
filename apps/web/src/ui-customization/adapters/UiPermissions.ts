/**
 * What the current actor may customise.
 *
 * The interface exists so that no component names a role or evaluates a
 * permission itself. Screens ask this layer; the answer comes from whatever
 * implementation is installed.
 */
export interface UiPermissions {
  canManagePlatformUi(): boolean;
  canManageTenantUi(): boolean;
}
