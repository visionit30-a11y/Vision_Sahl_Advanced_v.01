import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { DesignSystemPage } from '../pages/DesignSystemPage';
import { LoginPage } from '../pages/LoginPage';
import { HomePage } from '../pages/HomePage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { AppLayout } from './AppLayout';
import { AppProviders } from './AppProviders';

export function App() {
  return (
    <BrowserRouter>
      <AppProviders>
        <AppLayout>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/design-system" element={<DesignSystemPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppLayout>
      </AppProviders>
    </BrowserRouter>
  );
}
