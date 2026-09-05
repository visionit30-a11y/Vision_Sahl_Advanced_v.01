import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '../i18n';
import { PrintSpecimen } from '../pages/design-system/specimens/PrintSpecimen';
import { TableSpecimen } from '../pages/design-system/specimens/TableSpecimen';
import { PRINT_PRESET_IDS, TABLE_PRESET_IDS } from '../ui-customization/contract/presets';
import { renderWithProviders } from '../test/renderWithProviders';

afterEach(() => {
  delete document.documentElement.dataset.tablePreset;
  delete document.documentElement.dataset.printPreset;
});

/**
 * The specimens have no behaviour to break, so what these check is that the
 * semantic structure a screen reader will walk does not move when a preset
 * changes - the structure the table engine will inherit later.
 */
describe.each(TABLE_PRESET_IDS)('table specimen under %s', (preset) => {
  function renderUnderPreset() {
    document.documentElement.dataset.tablePreset = preset;
    return renderWithProviders(<TableSpecimen />);
  }

  it('keeps one table with a caption', () => {
    renderUnderPreset();

    expect(screen.getByRole('table')).toHaveAccessibleName(i18n.t('designSystem:table.caption'));
  });

  it('keeps four column headers', () => {
    renderUnderPreset();

    expect(screen.getAllByRole('columnheader')).toHaveLength(4);
  });

  it('keeps five data rows, a header row and a total row', () => {
    renderUnderPreset();

    expect(screen.getAllByRole('row')).toHaveLength(7);
    expect(screen.getByText(i18n.t('designSystem:table.total'))).toBeInTheDocument();
  });
});

describe.each(PRINT_PRESET_IDS)('print specimen under %s', (preset) => {
  function renderUnderPreset() {
    document.documentElement.dataset.printPreset = preset;
    return renderWithProviders(<PrintSpecimen />);
  }

  it('exposes the surface the print stylesheet targets', () => {
    const { container } = renderUnderPreset();

    expect(container.querySelector('[data-print-surface]')).not.toBeNull();
  });

  it('keeps the title, the metadata line and both footer slots', () => {
    renderUnderPreset();

    expect(screen.getByRole('heading')).toHaveTextContent(i18n.t('designSystem:print.titleSlot'));
    expect(screen.getByText(i18n.t('designSystem:print.metaSlot'))).toBeInTheDocument();
    expect(screen.getByText(i18n.t('designSystem:print.signatureSlot'))).toBeInTheDocument();
    expect(screen.getByText(i18n.t('designSystem:print.pageNumberSlot'))).toBeInTheDocument();
  });

  it('carries the table specimen onto the page', () => {
    renderUnderPreset();

    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
