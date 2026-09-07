import { createHash, randomBytes } from 'node:crypto';
import { createServer } from 'node:http';

const allowedOrigin = 'http://127.0.0.1:5173';
const sessions = new Map();
const digest = (value) => createHash('sha256').update(value).digest('hex');
const token = () => randomBytes(32).toString('base64url');
const json = (response, status, body, headers = {}) => {
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  response.end(JSON.stringify(body));
};
const bearerFrom = (request) =>
  /(?:^|; )__Host-sahl_session=([^;]+)/.exec(request.headers.cookie ?? '')?.[1];
const sessionFrom = (request) => sessions.get(digest(bearerFrom(request) ?? ''));
const readBody = async (request) => {
  let body = '';
  for await (const chunk of request) body += chunk;
  return body ? JSON.parse(body) : {};
};
const validUnsafe = (request, response, session) => {
  if (request.headers.origin !== allowedOrigin) {
    json(response, 403, { code: 'origin_rejected' });
    return false;
  }
  if (!session || request.headers['x-csrf-token'] !== session.csrf) {
    json(response, 403, { code: 'csrf_rejected' });
    return false;
  }
  return true;
};

createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', 'http://127.0.0.1');
  if (url.pathname === '/auth/test/session') {
    const bearer = token();
    const session = { csrf: token(), membership: 'membership-1' };
    sessions.set(digest(bearer), session);
    json(
      response,
      200,
      { ok: true },
      {
        'Set-Cookie': `__Host-sahl_session=${bearer}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      },
    );
    return;
  }
  const bearer = bearerFrom(request);
  const session = sessionFrom(request);
  if (url.pathname === '/auth/csrf' && request.method === 'GET') {
    if (!session) return json(response, 401, { code: 'invalid_session' });
    return json(response, 200, {}, { 'X-CSRF-Token': session.csrf });
  }
  if (url.pathname === '/auth/me' && request.method === 'GET') {
    if (!session) return json(response, 401, { code: 'invalid_session' });
    return json(response, 200, {
      id: 'user-1',
      email: 'member@example.test',
      selectedMembershipId: session.membership,
    });
  }
  if (url.pathname === '/auth/memberships' && request.method === 'GET') {
    if (!session) return json(response, 401, { code: 'invalid_session' });
    return json(response, 200, [
      { id: 'membership-1', tenantId: 'tenant-1', tenantName: 'One' },
      { id: 'membership-2', tenantId: 'tenant-2', tenantName: 'Two' },
    ]);
  }
  if (url.pathname === '/auth/tenant/switch' && request.method === 'POST') {
    if (!validUnsafe(request, response, session)) return;
    const selected = (await readBody(request)).membership_id;
    if (!['membership-1', 'membership-2'].includes(selected)) {
      return json(response, 403, { code: 'membership_denied' });
    }
    const nextBearer = token();
    const next = { csrf: token(), membership: selected };
    sessions.delete(digest(bearer ?? ''));
    sessions.set(digest(nextBearer), next);
    return json(
      response,
      200,
      {},
      {
        'Set-Cookie': `__Host-sahl_session=${nextBearer}; Path=/; Secure; HttpOnly; SameSite=Lax`,
        'X-CSRF-Token': next.csrf,
      },
    );
  }
  if (url.pathname === '/auth/logout' && request.method === 'POST') {
    if (!validUnsafe(request, response, session)) return;
    sessions.delete(digest(bearer ?? ''));
    return json(
      response,
      200,
      {},
      {
        'Set-Cookie': '__Host-sahl_session=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0',
      },
    );
  }
  if (url.pathname === '/auth/test/unsafe' && request.method === 'POST') {
    if (
      session &&
      request.headers['x-expected-membership-id'] &&
      request.headers['x-expected-membership-id'] !== session.membership
    ) {
      return json(
        response,
        409,
        { code: 'tenant_context_changed' },
        {
          'X-Auth-Error': 'tenant_context_changed',
        },
      );
    }
    if (!validUnsafe(request, response, session)) return;
    return json(response, 200, { membership: session.membership });
  }
  json(response, 404, { code: 'not_found' });
}).listen(8017, '127.0.0.1');
