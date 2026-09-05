import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/500.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import '@fontsource/ibm-plex-sans-arabic/700.css';
import './styles/index.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/router';
import { applyPalette, readStoredPalette } from './app/palette';
import i18n, { directionOf } from './i18n';

// Set language, direction and palette before the first paint.
document.documentElement.lang = i18n.language;
document.documentElement.dir = directionOf(i18n.language);
applyPalette(readStoredPalette());

const container = document.getElementById('root');

if (!container) {
  throw new Error('Root container #root was not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
