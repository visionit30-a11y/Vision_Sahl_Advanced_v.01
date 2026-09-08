import { createServer } from 'node:net';

const FRONTEND_PORT = 5187;
const BACKEND_URL = 'http://127.0.0.1:8010';
const requiredOperations = [
  ['get', '/auth/csrf'],
  ['get', '/auth/me'],
  ['get', '/auth/memberships'],
  ['post', '/auth/tenant/switch'],
  ['post', '/auth/logout'],
  ['get', '/ui-settings/effective'],
  ['get', '/ui-settings/user'],
  ['put', '/ui-settings/user'],
  ['delete', '/ui-settings/user'],
  ['get', '/ui-settings/tenant'],
  ['put', '/ui-settings/tenant'],
  ['delete', '/ui-settings/tenant'],
];

async function assertPortAvailable(host) {
  await new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once('error', (error) => {
      if (host === '::1' && error.code === 'EADDRNOTAVAIL') {
        resolve();
        return;
      }
      reject(
        new Error(
          `Browser test port ${FRONTEND_PORT} is unavailable on ${host}. Stop only a verified project-owned test process manually; no process was terminated and no alternative port will be selected.`,
        ),
      );
    });
    probe.listen({ host, port: FRONTEND_PORT, exclusive: true }, () => {
      probe.close((error) => (error ? reject(error) : resolve()));
    });
  });
}

async function readBackendJson(path) {
  let response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      signal: AbortSignal.timeout(5000),
      redirect: 'error',
      cache: 'no-store',
    });
  } catch {
    throw new Error(`Real FastAPI readiness failed at ${BACKEND_URL}${path}.`);
  }
  if (!response.ok) {
    throw new Error(`Real FastAPI readiness failed at ${path}: HTTP ${response.status}.`);
  }
  try {
    return await response.json();
  } catch {
    throw new Error(`Real FastAPI readiness returned invalid JSON at ${path}.`);
  }
}

try {
  await assertPortAvailable('127.0.0.1');
  await assertPortAvailable('::1');
  const health = await readBackendJson('/health');
  if (health.status !== 'ok' || health.name !== 'Sahl Developer Platform') {
    throw new Error('Port 8010 did not identify the expected healthy Sahl FastAPI application.');
  }
  const database = await readBackendJson('/health/db');
  if (database.dependency !== 'postgresql' || database.status !== 'up') {
    throw new Error('The real FastAPI PostgreSQL dependency is not healthy.');
  }
  const schema = await readBackendJson('/openapi.json');
  if (!schema.openapi || schema.info?.title !== health.name) {
    throw new Error('Port 8010 did not return the expected FastAPI OpenAPI contract.');
  }
  const missing = requiredOperations.filter(([method, path]) => !schema.paths?.[path]?.[method]);
  if (missing.length > 0) {
    throw new Error(
      `Real FastAPI auth/UI contract is incomplete: ${missing.map(([method, path]) => `${method.toUpperCase()} ${path}`).join(', ')}. Browser execution is blocked; the fixture security server is not a substitute.`,
    );
  }
  process.stdout.write(
    `Real backend preflight passed: ${BACKEND_URL}, PostgreSQL healthy, auth/UI operations registered. Browser frontend: http://localhost:${FRONTEND_PORT}.\n`,
  );
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : 'Browser preflight failed.'}\n`);
  process.exitCode = 1;
}
