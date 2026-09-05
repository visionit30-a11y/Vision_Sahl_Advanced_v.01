import { join } from 'node:path';

import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

export const THEMES_DIRECTORY = join(SRC_ROOT, 'styles', 'themes');

export interface ThemeFile {
  /** Taken from the file name, which the guards also check against the selector. */
  id: string;
  path: string;
  relativePath: string;
  selectors: string[];
  declarations: Map<string, string>;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '');
}

/**
 * Reads the identity stylesheets as data. Parsing the real files, rather than a
 * duplicate table in TypeScript, is what makes these guards meaningful: a value
 * edited in CSS is the value they check.
 */
export function readThemeFiles(): ThemeFile[] {
  return collectFiles(THEMES_DIRECTORY, ['.css'])
    .filter((path) => !path.endsWith('index.css'))
    .map((path) => {
      const source = stripComments(readFile(path));
      const declarations = new Map<string, string>();

      for (const match of source.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
        declarations.set(match[1] ?? '', (match[2] ?? '').trim());
      }

      const selectors = [...source.matchAll(/\[data-theme='([^']+)'\]/g)].map(
        (match) => match[1] ?? '',
      );

      const relativePath = toRelative(path);

      return {
        id:
          relativePath
            .split('/')
            .pop()
            ?.replace(/\.css$/, '') ?? '',
        path,
        relativePath,
        selectors,
        declarations,
      };
    })
    .sort((left, right) => left.id.localeCompare(right.id));
}

function channel(value: number): number {
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance as defined by WCAG 2.1, from a six or three digit hex. */
export function relativeLuminance(hex: string): number {
  const digits = hex.trim().replace('#', '');
  const full =
    digits.length === 3
      ? digits
          .split('')
          .map((digit) => digit + digit)
          .join('')
      : digits;

  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    throw new Error(`Not a hex colour: ${hex}`);
  }

  const [red, green, blue] = [0, 2, 4].map((offset) =>
    channel(Number.parseInt(full.slice(offset, offset + 2), 16) / 255),
  );

  return 0.2126 * (red ?? 0) + 0.7152 * (green ?? 0) + 0.0722 * (blue ?? 0);
}

/** The WCAG contrast ratio between two colours, from 1 to 21. */
export function contrastRatio(foreground: string, background: string): number {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);

  return (lighter + 0.05) / (darker + 0.05);
}
