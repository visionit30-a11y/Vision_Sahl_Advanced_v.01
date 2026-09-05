import { useContext } from 'react';

import { UiCustomizationContext } from './UiCustomizationContext';
import type { UiCustomizationValue } from './UiCustomizationContext';

/**
 * The only way a screen reaches the customisation engine. It returns semantic
 * values and never colours, so no consumer learns an identity's name.
 */
export function useUiCustomization(): UiCustomizationValue {
  const value = useContext(UiCustomizationContext);

  if (!value) {
    throw new Error('useUiCustomization must be used inside UiCustomizationProvider');
  }

  return value;
}
