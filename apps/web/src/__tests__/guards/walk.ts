import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';

const IGNORED_DIRECTORIES = new Set(['node_modules', 'dist', 'coverage', '.vite']);

/**
 * Locates the web source directory without depending on import.meta.url, which
 * is not a file URL under every test environment, and without any absolute path
 * tied to one machine. Works from apps/web (npm scripts, CI) and from the
 * repository root, on Windows and on Linux alike.
 */
function findSourceRoot(): string {
  const candidates = ['src', join('apps', 'web', 'src')];
  let current = process.cwd();

  for (let depth = 0; depth < 6; depth += 1) {
    for (const candidate of candidates) {
      const sourceRoot = resolve(current, candidate);
      if (existsSync(join(sourceRoot, 'i18n', 'locales'))) {
        return sourceRoot;
      }
    }

    const parent = dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }

  throw new Error(`Could not locate the web source directory from ${process.cwd()}`);
}

export const SRC_ROOT = findSourceRoot();

export function collectFiles(directory: string, extensions: string[]): string[] {
  const found: string[] = [];

  for (const entry of readdirSync(directory)) {
    if (IGNORED_DIRECTORIES.has(entry)) {
      continue;
    }

    const fullPath = join(directory, entry);
    if (statSync(fullPath).isDirectory()) {
      found.push(...collectFiles(fullPath, extensions));
    } else if (extensions.some((extension) => entry.endsWith(extension))) {
      found.push(fullPath);
    }
  }

  return found;
}

export function readFile(path: string): string {
  return readFileSync(path, 'utf8');
}

export function toRelative(path: string): string {
  return relative(SRC_ROOT, path).replace(/\\/g, '/');
}

/** Test files legitimately contain literal text; production sources do not. */
export function isTestFile(path: string): boolean {
  const relativePath = toRelative(path);
  return /\.test\.tsx?$/.test(relativePath) || relativePath.startsWith('test/');
}
