/* eslint-disable react-refresh/only-export-components */

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import {
  authClient,
  type AuthClient,
  type AuthenticatedUser,
  type MembershipSummary,
  HttpRequestError,
  SessionInvalidError,
  TenantContextChangedError,
} from '../auth/client';

export type AppAuthStatus =
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'
  | 'tenant-not-selected'
  | 'no-membership'
  | 'forbidden'
  | 'session-expired'
  | 'error';

interface AppAuthContextValue {
  status: AppAuthStatus;
  user: AuthenticatedUser | null;
  memberships: MembershipSummary[];
  selectedMembershipId: string | null;
  selectedMembershipName: string;
  login(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
  switchMembership(membershipId: string): Promise<void>;
  refresh(): Promise<void>;
}

const DEFAULT_CONTEXT: AppAuthContextValue = {
  status: 'loading',
  user: null,
  memberships: [],
  selectedMembershipId: null,
  selectedMembershipName: '',
  login: async () => {
    throw new Error('Auth provider not mounted');
  },
  logout: async () => {},
  switchMembership: async () => {},
  refresh: async () => {},
};

const AppAuthContext = createContext<AppAuthContextValue>(DEFAULT_CONTEXT);

export type AppAuthTransport = Pick<
  AuthClient,
  'bootstrapCsrf' | 'login' | 'logout' | 'me' | 'memberships' | 'subscribe' | 'switchTenant'
>;

function normalizeSelectedMembership(
  user: AuthenticatedUser | null,
  memberships: MembershipSummary[],
): string | null {
  if (!user || !user.selectedMembershipId) return null;
  return memberships.some((membership) => membership.id === user.selectedMembershipId)
    ? user.selectedMembershipId
    : null;
}

export function AppAuthProvider({
  children,
  client = authClient,
}: {
  children: ReactNode;
  client?: AppAuthTransport;
}) {
  const [status, setStatus] = useState<AppAuthStatus>('loading');
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [memberships, setMemberships] = useState<MembershipSummary[]>([]);
  const [selectedMembershipId, setSelectedMembershipId] = useState<string | null>(null);
  const refreshInFlight = useRef<Promise<void> | null>(null);
  const hadAuthenticatedSession = useRef(false);
  const authOperationInFlight = useRef(false);

  const refresh = useCallback(() => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const request = (async () => {
      try {
        const currentUser = await client.me();
        await client.bootstrapCsrf();
        const currentMemberships = await client.memberships();
        const selected = normalizeSelectedMembership(currentUser, currentMemberships);

        setUser(currentUser);
        hadAuthenticatedSession.current = true;
        setMemberships(currentMemberships);
        setSelectedMembershipId(selected);

        if (currentMemberships.length === 0) {
          setStatus('no-membership');
        } else if (!selected) {
          setStatus('tenant-not-selected');
        } else {
          setStatus('authenticated');
        }
      } catch (error) {
        if (
          error instanceof TenantContextChangedError ||
          error instanceof SessionInvalidError ||
          (error instanceof HttpRequestError && error.status === 401)
        ) {
          setUser(null);
          setMemberships([]);
          setSelectedMembershipId(null);
          setStatus(hadAuthenticatedSession.current ? 'session-expired' : 'unauthenticated');
          return;
        }
        if (error instanceof HttpRequestError && [403, 423].includes(error.status)) {
          setStatus('forbidden');
          return;
        }
        setStatus('error');
      }
    })();
    refreshInFlight.current = request;
    void request.finally(() => {
      if (refreshInFlight.current === request) refreshInFlight.current = null;
    });
    return request;
  }, [client]);

  const login = useCallback(
    async (email: string, password: string) => {
      setStatus('loading');
      authOperationInFlight.current = true;
      try {
        await client.login(email, password);
        authOperationInFlight.current = false;
        await refresh();
      } catch (error) {
        authOperationInFlight.current = false;
        setStatus('unauthenticated');
        throw error;
      }
    },
    [client, refresh],
  );

  const switchMembership = useCallback(
    async (membershipId: string) => {
      setStatus('loading');
      authOperationInFlight.current = true;
      try {
        await client.switchTenant(membershipId);
        authOperationInFlight.current = false;
        await refresh();
      } catch (error) {
        authOperationInFlight.current = false;
        await refresh();
        throw error;
      }
    },
    [client, refresh],
  );

  const logout = useCallback(async () => {
    authOperationInFlight.current = true;
    try {
      await client.logout();
    } finally {
      authOperationInFlight.current = false;
      setUser(null);
      hadAuthenticatedSession.current = false;
      setMemberships([]);
      setSelectedMembershipId(null);
      setStatus('unauthenticated');
    }
  }, [client]);

  useEffect(() => {
    const unsubscribe = client.subscribe((event) => {
      if (authOperationInFlight.current) return;
      if (event === 'invalid') {
        void refresh().catch(() => undefined);
        return;
      }
      if (event === 'changed') {
        void refresh().catch(() => undefined);
      }
    });

    void refresh();
    return unsubscribe;
  }, [client, refresh]);

  const selectedMembershipName = useMemo(() => {
    return (
      memberships.find((membership) => membership.id === selectedMembershipId)?.tenantName ?? ''
    );
  }, [memberships, selectedMembershipId]);

  const value = useMemo<AppAuthContextValue>(
    () => ({
      status,
      user,
      memberships,
      selectedMembershipId,
      selectedMembershipName,
      login,
      logout,
      switchMembership,
      refresh,
    }),
    [
      status,
      user,
      memberships,
      selectedMembershipId,
      selectedMembershipName,
      login,
      logout,
      switchMembership,
      refresh,
    ],
  );

  return <AppAuthContext.Provider value={value}>{children}</AppAuthContext.Provider>;
}

export function useAppAuth() {
  return useContext(AppAuthContext);
}
