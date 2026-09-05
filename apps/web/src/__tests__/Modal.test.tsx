import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Modal } from '../design-system';
import { renderWithProviders } from '../test/renderWithProviders';

describe('Modal', () => {
  it('renders nothing while closed', () => {
    renderWithProviders(
      <Modal open={false} title="Confirm" closeLabel="Close" onClose={vi.fn()}>
        <p>Body</p>
      </Modal>,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exposes an accessible dialog when open', () => {
    renderWithProviders(
      <Modal open title="Confirm" closeLabel="Close" onClose={vi.fn()}>
        <p>Body</p>
      </Modal>,
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Confirm');
  });

  it('closes on Escape and on the close control', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <Modal open title="Confirm" closeLabel="Close" onClose={onClose}>
        <p>Body</p>
      </Modal>,
    );

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
