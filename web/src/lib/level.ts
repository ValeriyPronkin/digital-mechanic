/** The mechanic's level (issue #17): «Опытный» — the value, the tool and the page; «Пошагово» — numbered steps,
 *  safety, plain words. Kept on the device; the same key as the first page («short» there meant «expert»). */
export type Level = 'expert' | 'steps'

export const LEVEL_KEY = 'dm-level'

type Store = Pick<Storage, 'getItem' | 'setItem'>

const storage = (): Store | null => (typeof localStorage === 'undefined' ? null : localStorage)

export function getLevel(store: Store | null = storage()): Level {
  const v = store?.getItem(LEVEL_KEY)
  return v === 'expert' || v === 'short' ? 'expert' : 'steps'
}

export function setLevel(level: Level, store: Store | null = storage()): void {
  store?.setItem(LEVEL_KEY, level)
}
