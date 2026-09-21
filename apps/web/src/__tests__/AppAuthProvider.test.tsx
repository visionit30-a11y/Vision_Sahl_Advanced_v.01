import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AuthChange, AuthenticatedUser, MembershipSummary } from '../auth/client';
import { SessionInvalidError } from '../auth/client';
import { AppAuthProvider, type AppAuthTransport, useAppAuth } from '../app/auth-state';

interface AuthFixture {
  client: AppAuthTransport;
  emit(event: AuthChange): void;
  failSession(): void;
}

function fixture(
  memberships: MembershipSummary[],
  selectedMembershipId: string | null,
): AuthFixture {
  let selected = selectedMembershipId;
  let sessionFails = false;
  let listener: (event: AuthChange) => void = () => undefined;
  const user = (): AuthenticatedUser => ({
    id: '00000000-0000-0000-0000-000000000001',
    email: 'person@example.test',
    selectedMembershipId: selected,
  });

  const client: AppAuthTransport = {
    bootstrapCsrf: vi.fn(async () => undefined),
    login: vi.fn(async () => user()),
    logout: vi.fn(async () => undefined),
    me: vi.fn(async () => {
      if (sessionFails) throw new SessionInvalidError('expired');
      return user();
    }),
    memberships: vi.fn(async () => memberships),
    subscribe: vi.fn((next) => {
      listener = next;
      return () => {
        listener = () => undefined;
      };
    }),
    switchTenant: vi.fn(async (membershipId: string) => {
      selected = membershipId;
      return user();
    }),
  };

  return {
    client,
    emit: (event) => listener(event),
    failSession: () => {
      sessionFails = true;
    },
  };
}

function Probe() {
  const auth = useAppAuth();
  return (
    <>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="membership-count">{auth.memberships.length}</span>
      <button
        onClick={() => {
          void auth.switchMembership('00000000-0000-0000-0000-000000000010');
        }}
      >
        switch
      </button>
    </>
  );
}

const membership: MembershipSummary = {
  id: '00000000-0000-0000-0000-000000000010',
  tenantId: '00000000-0000-0000-0000-000000000020',
  tenantName: 'Tenant A',
};

describe('application authentication state', () => {
  it('loads memberships for a fresh session and requires explicit tenant selection', async () => {
    const auth = fixture([membership], null);
    render(
      <AppAuthProvider client={auth.client}>
        <Probe />
      </AppAuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('tenant-not-selected'),
    );
    expect(screen.getByTestId('membership-count')).toHaveTextContent('1');
    expect(auth.client.memberships).toHaveBeenCalledOnce();
  });

  it('shows no-membership only when the trusted list is empty', async () => {
    const auth = fixture([], null);
    render(
      <AppAuthProvider client={auth.client}>
        <Probe />
      </AppAuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('no-membership'));
    expect(screen.getByTestId('membership-count')).toHaveTextContent('0');
  });

  it('selects a membership explicitly and refreshes the authenticated shell state', async () => {
    const auth = fixture([membership], null);
    render(
      <AppAuthProvider client={auth.client}>
        <Probe />
      </AppAuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('tenant-not-selected'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'switch' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(auth.client.switchTenant).toHaveBeenCalledWith(membership.id);
  });

  it('distinguishes an expired authenticated session from an anonymous visit', async () => {
    const auth = fixture([membership], membership.id);
    render(
      <AppAuthProvider client={auth.client}>
        <Probe />
      </AppAuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    auth.failSession();
    await act(async () => {
      auth.emit('invalid');
    });

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('session-expired'));
  });
});
