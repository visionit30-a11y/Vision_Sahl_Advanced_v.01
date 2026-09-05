import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';

import { StatusBarProvider } from '../design-system';
import { UiCustomizationProvider } from '../ui-customization';

export function renderWithProviders(ui: ReactElement, route = '/') {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[route]}>
        <UiCustomizationProvider>
          <StatusBarProvider>{children}</StatusBarProvider>
        </UiCustomizationProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper });
}
