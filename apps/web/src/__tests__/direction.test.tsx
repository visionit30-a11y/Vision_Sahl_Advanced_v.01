import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../app/AppProviders';
import i18n from '../i18n';

afterEach(async () => {
  await i18n.changeLanguage('ar');
});

describe('language and direction', () => {
  it('starts in Arabic with a right-to-left document', () => {
    render(
      <AppProviders>
        <span />
      </AppProviders>,
    );

    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('switches the document to left-to-right for English', async () => {
    render(
      <AppProviders>
        <span />
      </AppProviders>,
    );

    await act(async () => {
      await i18n.changeLanguage('en');
    });

    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });
});
