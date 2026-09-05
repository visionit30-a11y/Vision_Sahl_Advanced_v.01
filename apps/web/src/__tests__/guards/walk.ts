import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

/** src/ — resolved from this file so the guards work on any machine. */
export const SRC_ROOT = fileURLToPath(new URL('../..', import.meta.url));

const IGNORED_DIRECTORIES = new Set(['node_modules', 'dist', 'coverage']);

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
