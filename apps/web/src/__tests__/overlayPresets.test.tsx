import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Menu, Modal } from '../design-system';
import { OVERLAY_PRESET_IDS } from '../ui-customization/contract/presets';
import { renderWithProviders } from '../test/renderWithProviders';

afterEach(() => {
  delete document.documentElement.dataset.overlayPreset;
});

/**
 * The dialog and the menu carry the behaviour that costs the most to break:
 * the accessible role, the Escape route out, the keyboard path through a menu.
 * None of it lives in a stylesheet, and these run under every preset to keep it
 * that way.
 */
describe.each(OVERLAY_PRESET_IDS)('overlay behaviour under %s', (preset) => {
  function renderUnderPreset(ui: Parameters<typeof renderWithProviders>[0]) {
    document.documentElement.dataset.overlayPreset = preset;
    return renderWithProviders(ui);
  }

  it('renders nothing while the dialog is closed', () => {
    renderUnderPreset(
      <Modal open={false} title="Confirm" closeLabel="Close" onClose={vi.fn()}>
        <p>Body</p>
      </Modal>,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exposes an accessible modal dialog when open', () => {
    renderUnderPreset(
      <Modal open title="Confirm" closeLabel="Close" onClose={vi.fn()}>
        <p>Body</p>
      </Modal>,
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Confirm');
  });

  it('closes the dialog on Escape and on the close control', () => {
    const onClose = vi.fn();
    renderUnderPreset(
      <Modal open title="Confirm" closeLabel="Close" onClose={onClose}>
        <p>Body</p>
      </Modal>,
    );

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('opens a menu, reports its state and runs the chosen item', () => {
    const onSelect = vi.fn();
    renderUnderPreset(<Menu label="Actions" items={[{ id: 'edit', label: 'Edit', onSelect }]} />);

    const trigger = screen.getByRole('button', { name: /Actions/ });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes a menu on Escape', () => {
    renderUnderPreset(
      <Menu label="Actions" items={[{ id: 'edit', label: 'Edit', onSelect: vi.fn() }]} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Actions/ }));
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
