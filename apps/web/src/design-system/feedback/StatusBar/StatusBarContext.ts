import { createContext, useContext } from 'react';

import type { StatusBarActions, StatusMessage } from './statusBarTypes';

export const StatusBarActionsContext = createContext<StatusBarActions | null>(null);
export const StatusBarMessageContext = createContext<StatusMessage | null>(null);

/**
 * The only way a screen reports the outcome of an operation.
 * Field validation stays next to the field and never comes through here.
 */
export function useStatusBar(): StatusBarActions {
  const actions = useContext(StatusBarActionsContext);
  if (!actions) {
    throw new Error('useStatusBar must be used inside StatusBarProvider');
  }
  return actions;
}

export function useStatusMessage(): StatusMessage | null {
  return useContext(StatusBarMessageContext);
}
