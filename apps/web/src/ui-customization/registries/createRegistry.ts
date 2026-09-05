/**
 * A registry keeps the list of available options in one place, so a screen asks
 * "what is available" instead of carrying a chain of conditionals. Adding an
 * option is one entry here, never an edit inside a component.
 */
export interface RegistryEntry {
  id: string;
}

export interface Registry<T extends RegistryEntry> {
  list: () => readonly T[];
  get: (id: string) => T | undefined;
  has: (id: string) => boolean;
  ids: () => readonly string[];
}

export function createRegistry<T extends RegistryEntry>(entries: readonly T[]): Registry<T> {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));

  return {
    list: () => entries,
    get: (id) => byId.get(id),
    has: (id) => byId.has(id),
    ids: () => entries.map((entry) => entry.id),
  };
}
