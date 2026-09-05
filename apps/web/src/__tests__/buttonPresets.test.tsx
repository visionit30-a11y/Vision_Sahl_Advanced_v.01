import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Button } from '../design-system';
import { BUTTON_PRESET_IDS } from '../ui-customization/contract/presets';
import { renderWithProviders } from '../test/renderWithProviders';

afterEach(() => {
  delete document.documentElement.dataset.buttonPreset;
});

/**
 * A preset decides how a button looks and nothing else. Running the same
 * assertions under all five is what turns that from a claim into a fact: if one
 * of them ever reached behaviour, exactly one of these would fail.
 */
describe.each(BUTTON_PRESET_IDS)('button behaviour under %s', (preset) => {
  function renderUnderPreset(ui: Parameters<typeof renderWithProviders>[0]) {
    document.documentElement.dataset.buttonPreset = preset;
    return renderWithProviders(ui);
  }

  it('reacts to a click', () => {
    const onClick = vi.fn();
    renderUnderPreset(<Button onClick={onClick}>Save</Button>);

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('blocks interaction and announces work while loading', () => {
    const onClick = vi.fn();
    renderUnderPreset(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    );

    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');

    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('refuses a click while disabled', () => {
    const onClick = vi.fn();
    renderUnderPreset(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it('keeps the same API and the same accessible name', () => {
    renderUnderPreset(<Button iconStart="check">Save</Button>);

    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toBeEnabled();
  });
});
