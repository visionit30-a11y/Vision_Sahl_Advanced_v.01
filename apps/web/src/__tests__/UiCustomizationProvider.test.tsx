import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { UiPermissions } from '../ui-customization/adapters/UiPermissions';
import type { UiSettingsSource } from '../ui-customization/adapters/UiSettingsSource';
import type { UiSettingsPatch } from '../ui-customization/contract/settings';
import { UiCustomizationProvider } from '../ui-customization/UiCustomizationProvider';
import { useUiCustomization } from '../ui-customization/useUiCustomization';

const TENANT = 'test-tenant';

function memorySource(initial: {
  platform?: UiSettingsPatch | null;
  tenant?: UiSettingsPatch | null;
}): UiSettingsSource {
  let platform = initial.platform ?? null;
  let tenant = initial.tenant ?? null;

  return {
    readPlatform: () => Promise.resolve(platform),
    readTenant: () => Promise.resolve(tenant),
    writePlatform: (patch) => {
      platform = patch;
      return Promise.resolve();
    },
    writeTenant: (_tenantId, patch) => {
      tenant = patch;
      return Promise.resolve();
    },
  };
}

const allow: UiPermissions = {
  canManagePlatformUi: () => true,
  canManageTenantUi: () => true,
};

const denyTenant: UiPermissions = {
  canManagePlatformUi: () => true,
  canManageTenantUi: () => false,
};

function Probe() {
  const { settings, origin, canManage, setSetting, clearSetting } = useUiCustomization();

  return (
    <div>
      <span data-testid="theme">{settings.theme}</span>
      <span data-testid="origin">{origin.theme}</span>
      <span data-testid="tenant-allowed">{String(canManage('tenant'))}</span>
      <button
        type="button"
        onClick={() => {
          void setSetting('tenant', 'theme', 'sand-warm');
        }}
      >
        set-tenant
      </button>
      <button
        type="button"
        onClick={() => {
          void clearSetting('tenant', 'theme');
        }}
      >
        clear-tenant
      </button>
    </div>
  );
}

function renderProvider(source: UiSettingsSource, permissions: UiPermissions = allow) {
  return render(
    <UiCustomizationProvider source={source} permissions={permissions} tenantId={TENANT}>
      <Probe />
    </UiCustomizationProvider>,
  );
}

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe('ui customisation provider', () => {
  it('writes the resolved identity onto the document element', async () => {
    renderProvider(memorySource({ platform: { theme: 'navy-institutional' } }));

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('navy-institutional');
    });
    expect(screen.getByTestId('origin')).toHaveTextContent('platform');
  });

  it('applies a tenant choice over the platform default and repaints at once', async () => {
    renderProvider(memorySource({ platform: { theme: 'navy-institutional' } }));

    await waitFor(() => {
      expect(screen.getByTestId('origin')).toHaveTextContent('platform');
    });

    fireEvent.click(screen.getByRole('button', { name: 'set-tenant' }));

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('sand-warm');
    });
    expect(screen.getByTestId('origin')).toHaveTextContent('tenant');
  });

  it('returns to the inherited value when the tenant customisation is removed', async () => {
    renderProvider(
      memorySource({ platform: { theme: 'navy-institutional' }, tenant: { theme: 'sand-warm' } }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('origin')).toHaveTextContent('tenant');
    });

    fireEvent.click(screen.getByRole('button', { name: 'clear-tenant' }));

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('navy-institutional');
    });
    expect(screen.getByTestId('origin')).toHaveTextContent('platform');
  });

  it('does not write a scope the permissions layer refuses', async () => {
    renderProvider(memorySource({ platform: { theme: 'navy-institutional' } }), denyTenant);

    await waitFor(() => {
      expect(screen.getByTestId('tenant-allowed')).toHaveTextContent('false');
    });

    fireEvent.click(screen.getByRole('button', { name: 'set-tenant' }));
    await Promise.resolve();

    expect(document.documentElement.dataset.theme).toBe('navy-institutional');
    expect(screen.getByTestId('origin')).toHaveTextContent('platform');
  });
});
