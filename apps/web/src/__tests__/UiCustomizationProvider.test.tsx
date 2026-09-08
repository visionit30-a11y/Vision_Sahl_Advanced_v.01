import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AuthChange } from '../auth/client';
import { HttpRequestError, SessionInvalidError } from '../auth/client';
import type {
  SettingsSnapshot,
  UiSettingsSource,
} from '../ui-customization/adapters/UiSettingsSource';
import { BUILT_IN_UI_SETTINGS } from '../ui-customization/contract/settings';
import { UiCustomizationProvider } from '../ui-customization/UiCustomizationProvider';
import { useUiCustomization } from '../ui-customization/useUiCustomization';
import { resolveUiSettings } from '../ui-customization/resolution/resolveUiSettings';

function fixture() {
  let user: SettingsSnapshot['layers']['user'] = null;
  let tenant: SettingsSnapshot['layers']['tenant'] = {
    settings: { theme: 'navy-institutional' },
    version: 1,
  };
  let listener: (event: AuthChange) => void = () => undefined;
  const snapshot = (): SettingsSnapshot => {
    const resolved = resolveUiSettings({
      builtIn: BUILT_IN_UI_SETTINGS,
      tenant: tenant?.settings,
      user: user?.settings,
    });
    return { ...resolved, layers: { user, tenant }, allowed: { user: true, tenant: true } };
  };
  const source: UiSettingsSource = {
    load: vi.fn(async () => snapshot()),
    write: vi.fn(async (scope, settings, version) => {
      const value = { settings, version: (version ?? 0) + 1 };
      if (scope === 'user') user = value;
      else tenant = value;
    }),
    remove: vi.fn(async (scope) => {
      if (scope === 'user') user = null;
      else tenant = null;
    }),
    subscribe: (fn) => {
      listener = fn;
      return () => {
        listener = () => undefined;
      };
    },
  };
  return { source, snapshot, change: (event: AuthChange) => listener(event) };
}
function Probe() {
  const ui = useUiCustomization();
  return (
    <>
      <span data-testid="theme">{ui.settings.theme}</span>
      <span data-testid="origin">{ui.origin.theme}</span>
      <span data-testid="status">{ui.status}</span>
      <button
        disabled={!ui.canManage('user')}
        onClick={() => {
          void ui.setSetting('user', 'theme', 'sand-warm');
        }}
      >
        user
      </button>
      <button
        disabled={!ui.canManage('tenant')}
        onClick={() => {
          void ui.setSetting('tenant', 'theme', 'green-institutional');
        }}
      >
        tenant
      </button>
      <button
        onClick={() => {
          void ui.clearSetting('user', 'theme');
        }}
      >
        delete
      </button>
      <button
        onClick={() => {
          void ui.reload();
        }}
      >
        reload
      </button>
    </>
  );
}
function mount(source: UiSettingsSource) {
  return render(
    <UiCustomizationProvider source={source}>
      <Probe />
    </UiCustomizationProvider>,
  );
}
async function ready() {
  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'));
}

describe('server-backed settings provider', () => {
  it('fetches initially and on remount, then applies server origin', async () => {
    const { source } = fixture();
    const view = mount(source);
    await ready();
    expect(screen.getByTestId('theme')).toHaveTextContent('navy-institutional');
    expect(screen.getByTestId('origin')).toHaveTextContent('tenant');
    view.unmount();
    mount(source);
    await ready();
    expect(source.load).toHaveBeenCalledTimes(2);
  });
  it('saves user and tenant layers with versions and deletes back to inheritance', async () => {
    const { source } = fixture();
    mount(source);
    await ready();
    fireEvent.click(screen.getByText('user'));
    await ready();
    expect(source.write).toHaveBeenCalledWith('user', { theme: 'sand-warm' }, null);
    expect(screen.getByTestId('origin')).toHaveTextContent('user');
    fireEvent.click(screen.getByRole('button', { name: 'tenant' }));
    await ready();
    expect(source.write).toHaveBeenCalledWith('tenant', { theme: 'green-institutional' }, 1);
    expect(screen.getByTestId('theme')).toHaveTextContent('sand-warm');
    fireEvent.click(screen.getByText('delete'));
    await ready();
    expect(source.remove).toHaveBeenCalledWith('user', 1);
    expect(screen.getByTestId('theme')).toHaveTextContent('green-institutional');
  });
  it.each([['changed'], ['invalid']] as const)(
    'clears old session settings on %s',
    async (event) => {
      const f = fixture();
      mount(f.source);
      await ready();
      vi.mocked(f.source.load).mockImplementation(() => new Promise(() => undefined));
      act(() => f.change(event));
      expect(screen.getByTestId('theme')).toHaveTextContent('teal-calm');
      expect(screen.getByText('user')).toBeDisabled();
      expect(screen.getByTestId('status')).toHaveTextContent(
        event === 'invalid' ? 'unauthorized' : 'loading',
      );
    },
  );
  it('discards an old tenant response arriving after rotation', async () => {
    const f = fixture();
    let complete!: (value: SettingsSnapshot) => void;
    vi.mocked(f.source.load).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    mount(f.source);
    const fresh = {
      ...f.snapshot(),
      settings: { ...BUILT_IN_UI_SETTINGS, theme: 'green-institutional' as const },
    };
    vi.mocked(f.source.load).mockResolvedValue(fresh);
    act(() => f.change('changed'));
    await ready();
    await act(async () => {
      complete(f.snapshot());
    });
    expect(screen.getByTestId('theme')).toHaveTextContent('green-institutional');
  });
  it.each([
    [new HttpRequestError(409), 'conflict'],
    [new HttpRequestError(403), 'forbidden'],
    [new SessionInvalidError(), 'unauthorized'],
    [new TypeError('network'), 'error'],
  ])('fails visibly after rejected write: %s', async (error, state) => {
    const f = fixture();
    mount(f.source);
    await ready();
    vi.mocked(f.source.write).mockRejectedValue(error);
    fireEvent.click(screen.getByText('user'));
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent(state as string));
    expect(screen.getByTestId('theme')).toHaveTextContent('teal-calm');
    expect(screen.getByText('user')).toBeDisabled();
    fireEvent.click(screen.getByText('reload'));
    await ready();
  });
  it('uses server permission denials to disable controls', async () => {
    const f = fixture();
    vi.mocked(f.source.load).mockResolvedValue({
      ...f.snapshot(),
      allowed: { user: true, tenant: false },
    });
    mount(f.source);
    await ready();
    expect(screen.getByRole('button', { name: 'tenant' })).toBeDisabled();
    expect(screen.getByText('user')).toBeEnabled();
  });
  it('does not apply a change before the server confirms it', async () => {
    const f = fixture();
    mount(f.source);
    await ready();
    vi.mocked(f.source.write).mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(screen.getByText('user'));
    expect(screen.getByTestId('theme')).toHaveTextContent('navy-institutional');
    expect(screen.getByTestId('status')).toHaveTextContent('saving');
    expect(f.source.load).toHaveBeenCalledTimes(1);
  });
});
