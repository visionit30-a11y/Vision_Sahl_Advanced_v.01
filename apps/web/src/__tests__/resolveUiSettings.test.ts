import { describe, expect, it } from 'vitest';

import { BUILT_IN_UI_SETTINGS } from '../ui-customization/contract/settings';
import { resolveUiSettings } from '../ui-customization/resolution/resolveUiSettings';

describe('ui settings resolution', () => {
  it('falls back to the built-in layer when nothing is configured', () => {
    const { settings, origin } = resolveUiSettings({ builtIn: BUILT_IN_UI_SETTINGS });

    expect(settings).toEqual(BUILT_IN_UI_SETTINGS);
    expect(origin.theme).toBe('builtIn');
  });

  it('lets the platform layer override the built-in one', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: { theme: 'navy-institutional' },
    });

    expect(settings.theme).toBe('navy-institutional');
    expect(origin.theme).toBe('platform');
  });

  it('lets the tenant layer override the platform one', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: { theme: 'navy-institutional' },
      tenant: { theme: 'sand-warm' },
    });

    expect(settings.theme).toBe('sand-warm');
    expect(origin.theme).toBe('tenant');
  });

  it('accepts the user layer although the interface does not populate it yet', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: { theme: 'navy-institutional' },
      tenant: { theme: 'sand-warm' },
      user: { theme: 'slate-neutral' },
    });

    expect(settings.theme).toBe('slate-neutral');
    expect(origin.theme).toBe('user');
  });

  it('ignores an empty patch and keeps inheriting', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: { theme: 'navy-institutional' },
      tenant: {},
    });

    expect(settings.theme).toBe('navy-institutional');
    expect(origin.theme).toBe('platform');
  });

  it('ignores an unknown value instead of applying it', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: { theme: 'navy-institutional' },
      tenant: { theme: 'a-theme-from-an-older-release' } as never,
    });

    expect(settings.theme).toBe('navy-institutional');
    expect(origin.theme).toBe('platform');
  });

  it('treats a null layer as absent', () => {
    const { settings, origin } = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      platform: null,
      tenant: null,
    });

    expect(settings).toEqual(BUILT_IN_UI_SETTINGS);
    expect(origin.theme).toBe('builtIn');
  });
});
