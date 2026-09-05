import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBarRegion, useStatusBar } from '../design-system';
import i18n from '../i18n';
import { renderWithProviders } from '../test/renderWithProviders';

function Harness() {
  const { show, clear } = useStatusBar();

  return (
    <>
      <button
        type="button"
        onClick={() => {
          show({
            tone: 'success',
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

describe('status bar engine', () => {
  it('reserves its region before any message exists', () => {
    renderWithProviders(<Harness />);

    expect(screen.getByLabelText(i18n.t('status:region'))).toBeInTheDocument();
  });

  it('shows a message with a record link that opens in a separate tab', () => {
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole('button', { name: 'show' }));

    expect(screen.getByText(i18n.t('designSystem:samples.recordCreated'))).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'JE-000123' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('keeps the reserved region after the message is dismissed', () => {
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole('button', { name: 'show' }));
    fireEvent.click(screen.getByRole('button', { name: 'clear' }));

    expect(
      screen.queryByText(i18n.t('designSystem:samples.recordCreated')),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(i18n.t('status:region'))).toBeInTheDocument();
  });

  it('offers a dismiss control on a dismissible message', () => {
    renderWithProviders(<Harness />);

    fireEvent.click(screen.getByRole('button', { name: 'show' }));

    expect(screen.getByRole('button', { name: i18n.t('status:dismiss') })).toBeInTheDocument();
  });
});
