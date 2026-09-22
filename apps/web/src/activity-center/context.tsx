/* eslint-disable react-refresh/only-export-components */

import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from 'react';

import { activityCenterClient } from './client';

interface ActivityCenterState {
  unreadCount: number;
  reload(): Promise<void>;
}

const ActivityCenterContext = createContext<ActivityCenterState>({
  unreadCount: 0,
  reload: async () => undefined,
});

export function ActivityCenterProvider({ children }: { children: ReactNode }) {
  const [unreadCount, setUnreadCount] = useState(0);
  const reload = useCallback(async () => {
    const summary = await activityCenterClient.summary();
    setUnreadCount(summary.unread_count);
  }, []);
  useEffect(() => {
    void reload().catch(() => setUnreadCount(0));
  }, [reload]);
  return (
    <ActivityCenterContext.Provider value={{ unreadCount, reload }}>
      {children}
    </ActivityCenterContext.Provider>
  );
}

export function useActivityCenter(): ActivityCenterState {
  return useContext(ActivityCenterContext);
}
