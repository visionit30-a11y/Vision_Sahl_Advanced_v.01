import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  FRONTEND_PERMISSIONS,
  FrontendPermissionProvider,
  usePermissionSnapshot,
} from '../app/permission-state';
import { BUILT_IN_UI_SETTINGS } from '../ui-customization/contract/settings';
import { UiCustomizationContext } from '../ui-customization/UiCustomizationContext';
import type {
  SettingsStatus,
  UiCustomizationValue,
} from '../ui-customization/UiCustomizationContext';

function customization(
  status: SettingsStatus,
  user: boolean,
  tenant: boolean,
): UiCustomizationValue {
  return {
    settings: BUILT_IN_UI_SETTINGS,
    origin: {
      theme: 'builtIn',
      buttonPreset: 'builtIn',
      alertPreset: 'builtIn',
      overlayPreset: 'builtIn',
      tablePreset: 'builtIn',
      printPreset: 'builtIn',
    },
    layers: { user: null, tenant: null },
    ready: status === 'ready',
    status,
    reload: async () => undefined,
    canManage: (scope) => (scope === 'user' ? user : tenant),
    setSetting: async () => undefined,
    clearSetting: async () => undefined,
  };
}

function Probe() {
  const permissions = usePermissionSnapshot();
  return (
    <>
      <span data-testid="status">{permissions.status}</span>
      <span data-testid="user">
        {String(permissions.allows(FRONTEND_PERMISSIONS.manageOwnUiSettings))}
      </span>
      <span data-testid="tenant">
        {String(permissions.allows(FRONTEND_PERMISSIONS.manageTenantUiSettings))}
      </span>
      <span data-testid="unknown">{String(permissions.allows('tenant.unknown.read'))}</span>
    </>
  );
}

function mount(value: UiCustomizationValue) {
  return render(
    <UiCustomizationContext.Provider value={value}>
      <FrontendPermissionProvider>
        <Probe />
      </FrontendPermissionProvider>
    </UiCustomizationContext.Provider>,
  );
}

describe('frontend permission presentation', () => {
  it('derives only server-proven UI permissions and rejects unknown identifiers', () => {
    mount(customization('ready', true, false));

    expect(screen.getByTestId('status')).toHaveTextContent('ready');
    expect(screen.getByTestId('user')).toHaveTextContent('true');
    expect(screen.getByTestId('tenant')).toHaveTextContent('false');
    expect(screen.getByTestId('unknown')).toHaveTextContent('false');
  });

  it('fails closed before proof and retains presentation only for visible transient errors', () => {
    const view = mount(customization('loading', true, true));
    expect(screen.getByTestId('status')).toHaveTextContent('loading');
    expect(screen.getByTestId('user')).toHaveTextContent('false');

    view.rerender(
      <UiCustomizationContext.Provider value={customization('ready', true, true)}>
        <FrontendPermissionProvider>
          <Probe />
        </FrontendPermissionProvider>
      </UiCustomizationContext.Provider>,
    );
    expect(screen.getByTestId('user')).toHaveTextContent('true');

    view.rerender(
      <UiCustomizationContext.Provider value={customization('error', true, true)}>
        <FrontendPermissionProvider>
          <Probe />
        </FrontendPermissionProvider>
      </UiCustomizationContext.Provider>,
    );
    expect(screen.getByTestId('status')).toHaveTextContent('unavailable');
    expect(screen.getByTestId('user')).toHaveTextContent('true');
    expect(screen.getByTestId('tenant')).toHaveTextContent('true');
  });
});
