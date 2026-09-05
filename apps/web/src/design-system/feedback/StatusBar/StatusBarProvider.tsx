import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { StatusBarActionsContext, StatusBarMessageContext } from './StatusBarContext';
import { defaultDuration } from './statusBarTypes';
import type { StatusMessage } from './statusBarTypes';

export function StatusBarProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<StatusMessage | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const clear = useCallback(() => {
    clearTimer();
    setMessage(null);
  }, [clearTimer]);

  const show = useCallback(
    (next: StatusMessage) => {
      clearTimer();
      setMessage(next);

      const duration =
        next.durationMs === undefined ? defaultDuration(next.intent) : next.durationMs;
      if (duration !== null) {
        timerRef.current = window.setTimeout(() => {
          setMessage(null);
          timerRef.current = null;
        }, duration);
      }
    },
    [clearTimer],
  );

  useEffect(() => clearTimer, [clearTimer]);

  const actions = useMemo(() => ({ show, clear }), [show, clear]);

  return (
    <StatusBarActionsContext.Provider value={actions}>
      <StatusBarMessageContext.Provider value={message}>
        {children}
      </StatusBarMessageContext.Provider>
    </StatusBarActionsContext.Provider>
  );
}
