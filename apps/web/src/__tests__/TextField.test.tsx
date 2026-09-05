import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TextField } from '../design-system';
import { renderWithProviders } from '../test/renderWithProviders';

describe('TextField', () => {
  it('links its label to the control', () => {
    renderWithProviders(<TextField label="Organisation name" />);

    expect(screen.getByLabelText('Organisation name')).toBeInTheDocument();
  });

  it('describes the control with its hint', () => {
    renderWithProviders(<TextField label="Organisation name" hint="As written on the licence" />);

    expect(screen.getByLabelText('Organisation name')).toHaveAccessibleDescription(
      'As written on the licence',
    );
  });

  it('marks an invalid control and keeps the error next to the field', () => {
    renderWithProviders(<TextField label="Organisation name" error="This field is required" />);

    const input = screen.getByLabelText('Organisation name');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('This field is required');
  });
});
