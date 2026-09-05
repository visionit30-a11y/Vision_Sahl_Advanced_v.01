import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Menu } from '../design-system';
import { renderWithProviders } from '../test/renderWithProviders';

describe('Menu', () => {
  it('opens, reports its state and runs the chosen item', () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <Menu label="Actions" items={[{ id: 'edit', label: 'Edit', onSelect }]} />,
    );

    const trigger = screen.getByRole('button', { name: /Actions/ });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes on Escape', () => {
    renderWithProviders(
      <Menu label="Actions" items={[{ id: 'edit', label: 'Edit', onSelect: vi.fn() }]} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Actions/ }));
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
