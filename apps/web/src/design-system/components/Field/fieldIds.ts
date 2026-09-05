/**
 * Identifier helpers shared by every field component. They live apart from the
 * component so the module exports components only, which keeps fast refresh
 * working and the rule that enforces it quiet.
 */
export function hintId(id: string): string {
  return `${id}-hint`;
}

export function errorId(id: string): string {
  return `${id}-error`;
}

export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [hint ? hintId(id) : null, error ? errorId(id) : null].filter(Boolean);
  return ids.length > 0 ? ids.join(' ') : undefined;
}
