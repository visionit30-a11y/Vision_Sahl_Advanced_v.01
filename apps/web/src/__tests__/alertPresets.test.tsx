import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { InlineAlert, StatusBarRegion, useStatusBar } from '../design-system';
import type { StatusIntent } from '../design-system';
import i18n from '../i18n';
import { ALERT_PRESET_IDS } from '../ui-customization/contract/presets';
import { renderWithProviders } from '../test/renderWithProviders';

const INTENTS: StatusIntent[] = [
  'success',
  'saved',
  'updated',
  'deleted',
  'cancelled',
  'blocked',
  'warning',
  'error',
  'info',
];

function Harness({ intent }: { intent: StatusIntent }) {
  const { show, clear } = useStatusBar();

  return (
    <>
      <button
        type="button"
        onClick={() => {
          show({
            intent,
            messageKey: 'designSystem:samples.recordCreated',
            link: { label: 'JE-000123', href: '/entries/123' },
            durationMs: null,
          });
        }}
      >
        show
      </button>
      <button type="button" onClick={clear}>
        clear
      </button>
      <StatusBarRegion />
    </>
  );
}

afterEach(() => {
  delete document.documentElement.dataset.alertPreset;
});

/**
 * The reserved band, the message, its record link and its dismiss control are
 * the status bar's contract. A presentation preset may repaint them and may not
 * remove them, and every one of the five is held to that here.
 */
describe.each(ALERT_PRESET_IDS)('alert behaviour under %s', (preset) => {
  function renderUnderPreset(ui: Parameters<typeof renderWithProviders>[0]) {
    document.documentElement.dataset.alertPreset = preset;
    return renderWithProviders(ui);
  }

  it('reserves the region before any message exists', () => {
    renderUnderPreset(<Harness intent="saved" />);

    expect(screen.getByLabelText(i18n.t('status:region'))).toBeInTheDocument();
  });

  it('shows a message with a record link that opens in a separate tab', () => {
    renderUnderPreset(<Harness intent="saved" />);

    fireEvent.click(screen.getByRole('button', { name: 'show' }));

    expect(screen.getByText(i18n.t('designSystem:samples.recordCreated'))).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'JE-000123' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('keeps the reserved region after the message is dismissed', () => {
    renderUnderPreset(<Harness intent="saved" />);

    fireEvent.click(screen.getByRole('button', { name: 'show' }));
    fireEvent.click(screen.getByRole('button', { name: i18n.t('status:dismiss') }));

    expect(
      screen.queryByText(i18n.t('designSystem:samples.recordCreated')),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(i18n.t('status:region'))).toBeInTheDocument();
  });

  it('renders every intent without losing the message', () => {
    for (const intent of INTENTS) {
      const view = renderUnderPreset(<Harness intent={intent} />);

      fireEvent.click(screen.getByRole('button', { name: 'show' }));
      expect(screen.getByText(i18n.t('designSystem:samples.recordCreated'))).toBeInTheDocument();

      view.unmount();
    }
  });

  it('keeps the inline alert readable as a status region', () => {
    renderUnderPreset(
      <InlineAlert tone="neutral" title="Cancelled">
        Body
      </InlineAlert>,
    );

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
    expect(screen.getByText('Body')).toBeInTheDocument();
  });
});
