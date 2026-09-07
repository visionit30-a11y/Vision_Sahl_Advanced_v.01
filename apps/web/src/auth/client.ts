const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export interface MembershipSummary {
  id: string;
  tenantId: string;
  tenantName: string;
}

export interface AuthenticatedUser {
  id: string;
  email: string;
  selectedMembershipId: string | null;
}

export class SessionInvalidError extends Error {}
export class TenantContextChangedError extends Error {}
export class CsrfUnavailableError extends Error {}

interface AuthClientOptions {
  baseUrl?: string;
  fetcher?: typeof fetch;
  channel?: BroadcastChannel;
}

export class AuthClient {
  readonly #baseUrl: string;
  readonly #fetch: typeof fetch;
  readonly #channel: BroadcastChannel | undefined;
  #csrfToken: string | undefined;
  #selectedMembershipId: string | null = null;
  #generation = 0;

  constructor(options: AuthClientOptions = {}) {
    this.#baseUrl = options.baseUrl ?? '';
    this.#fetch = options.fetcher ?? globalThis.fetch.bind(globalThis);
    this.#channel =
      options.channel ??
      (typeof BroadcastChannel === 'undefined' ? undefined : new BroadcastChannel('sahl-auth'));
    this.#channel?.addEventListener('message', (event: MessageEvent<number>) => {
      if (event.data > this.#generation) this.#invalidate(event.data);
    });
  }

  async bootstrapCsrf(): Promise<void> {
    const response = await this.#request('/auth/csrf', { method: 'GET' }, false);
    this.#acceptCsrf(response);
  }

  async me(): Promise<AuthenticatedUser> {
    const response = await this.#request('/auth/me', { method: 'GET' });
    const user = (await response.json()) as AuthenticatedUser;
    this.#selectedMembershipId = user.selectedMembershipId;
    return user;
  }

  async memberships(): Promise<MembershipSummary[]> {
    const response = await this.#request('/auth/memberships', { method: 'GET' });
    return (await response.json()) as MembershipSummary[];
  }

  async switchTenant(membershipId: string): Promise<AuthenticatedUser> {
    const response = await this.#request('/auth/tenant/switch', {
      method: 'POST',
      body: JSON.stringify({ membership_id: membershipId }),
    });
    const rotatedCsrf = response.headers.get('X-CSRF-Token');
    this.#rotate();
    if (rotatedCsrf) this.#csrfToken = rotatedCsrf;
    return this.me();
  }

  async logout(): Promise<void> {
    await this.#request('/auth/logout', { method: 'POST' });
    this.#rotate();
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    return this.#request(path, init);
  }

  close(): void {
    this.#channel?.close();
  }

  async #request(path: string, init: RequestInit, requireSession = true): Promise<Response> {
    const method = (init.method ?? 'GET').toUpperCase();
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (init.body !== undefined) headers.set('Content-Type', 'application/json');
    if (UNSAFE_METHODS.has(method)) {
      if (!this.#csrfToken) throw new CsrfUnavailableError('CSRF bootstrap is required.');
      headers.set('X-CSRF-Token', this.#csrfToken);
      if (this.#selectedMembershipId) {
        headers.set('X-Expected-Membership-ID', this.#selectedMembershipId);
      }
    }
    const response = await this.#fetch(`${this.#baseUrl}${path}`, {
      ...init,
      method,
      headers,
      credentials: 'include',
      cache: 'no-store',
    });
    if (response.status === 401 && requireSession) {
      this.#invalidate(this.#generation + 1);
      throw new SessionInvalidError('The server-side session is no longer valid.');
    }
    if (
      response.status === 409 &&
      response.headers.get('X-Auth-Error') === 'tenant_context_changed'
    ) {
      this.#invalidate(this.#generation + 1);
      throw new TenantContextChangedError('The trusted tenant context changed.');
    }
    if (!response.ok) throw new Error(`Auth request failed with status ${response.status}.`);
    this.#acceptCsrf(response);
    return response;
  }

  #acceptCsrf(response: Response): void {
    const token = response.headers.get('X-CSRF-Token');
    if (token) this.#csrfToken = token;
  }

  #invalidate(generation: number): void {
    this.#generation = generation;
    this.#csrfToken = undefined;
    this.#selectedMembershipId = null;
  }

  #rotate(): void {
    this.#generation += 1;
    this.#csrfToken = undefined;
    this.#selectedMembershipId = null;
    this.#channel?.postMessage(this.#generation);
  }
}
