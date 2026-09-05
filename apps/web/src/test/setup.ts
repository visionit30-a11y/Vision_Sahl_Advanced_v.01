import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

import '@testing-library/jest-dom/vitest';

// Vitest runs without global test APIs in this project, so Testing Library
// cannot register its automatic cleanup. Without this, renders from earlier
// tests stay in the document and queries match duplicated elements.
afterEach(() => {
  cleanup();
});
