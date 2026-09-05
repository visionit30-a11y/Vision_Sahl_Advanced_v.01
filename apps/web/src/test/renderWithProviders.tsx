import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';

import { StatusBarProvider } from '../design-system';

export function renderWithProviders(ui: ReactElement, route = '/') {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[route]}>
        <StatusBarProvider>{children}</StatusBarProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper });
}
