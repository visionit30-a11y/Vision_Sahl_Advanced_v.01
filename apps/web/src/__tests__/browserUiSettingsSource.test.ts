import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  browserUiSettingsSource,
  readBootstrapUiSettings,
} from '../ui-customization/adapters/browserUiSettingsSource';
import { BUILT_IN_UI_SETTINGS } from '../ui-customization/contract/settings';

const TENANT = 'preview-tenant';

describe('browser settings source', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('reads back what it wrote for the platform layer', async () => {
    await browserUiSettingsSource.writePlatform({ theme: 'navy-institutional' });

    await expect(browserUiSettingsSource.readPlatform()).resolves.toEqual({
      theme: 'navy-institutional',
    });
  });

  it('keeps the tenant layer separate from the platform layer', async () => {
    await browserUiSettingsSource.writePlatform({ theme: 'navy-institutional' });
    await browserUiSettingsSource.writeTenant(TENANT, { theme: 'sand-warm' });

    await expect(browserUiSettingsSource.readTenant(TENANT)).resolves.toEqual({
      theme: 'sand-warm',
    });
    await expect(browserUiSettingsSource.readPlatform()).resolves.toEqual({
      theme: 'navy-institutional',
    });
  });

  it('removes the layer when it is written empty', async () => {
    await browserUiSettingsSource.writeTenant(TENANT, { theme: 'sand-warm' });
    await browserUiSettingsSource.writeTenant(TENANT, {});

    await expect(browserUiSettingsSource.readTenant(TENANT)).resolves.toBeNull();
  });

  it('reports no layer when there is no tenant', async () => {
    await expect(browserUiSettingsSource.readTenant(null)).resolves.toBeNull();
  });

  it('ignores a stored value an older release wrote', async () => {
    window.localStorage.setItem('sahl.ui.platform', JSON.stringify({ theme: 'c' }));

    await expect(browserUiSettingsSource.readPlatform()).resolves.toEqual({});
  });

  it('ignores unreadable stored content', async () => {
    window.localStorage.setItem('sahl.ui.platform', 'not json');

    await expect(browserUiSettingsSource.readPlatform()).resolves.toBeNull();
  });

  it('survives a browser that refuses to store', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage is full');
    });

    await expect(
      browserUiSettingsSource.writePlatform({ theme: 'sand-warm' }),
    ).resolves.toBeUndefined();
  });

  it('resolves the stored layers before the first paint', () => {
    window.localStorage.setItem(
      'sahl.ui.platform',
      JSON.stringify({ theme: 'navy-institutional' }),
    );
    window.localStorage.setItem(
      `sahl.ui.tenant.${TENANT}`,
      JSON.stringify({ theme: 'slate-neutral' }),
    );

    expect(readBootstrapUiSettings(TENANT).theme).toBe('slate-neutral');
    expect(readBootstrapUiSettings(null).theme).toBe('navy-institutional');
  });

  it('bootstraps to the built-in identity when nothing is stored', () => {
    expect(readBootstrapUiSettings(TENANT)).toEqual(BUILT_IN_UI_SETTINGS);
  });
});
