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

/** Whether the mechanic has already answered «Как объяснять?» (asked once, on the first visit). */
export function isLevelChosen(store: Store | null = storage()): boolean {
  const v = store?.getItem(LEVEL_KEY)
  return v === 'expert' || v === 'steps' || v === 'short'
}

export const LEVEL_EVENT = 'dm-level'

export function setLevel(level: Level, store: Store | null = storage()): void {
  store?.setItem(LEVEL_KEY, level)
  // the switch on the vehicle screen follows a choice made elsewhere (the first-visit question)
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(LEVEL_EVENT))
}

/** «Подробнее / Короче» (#17): re-ask with the other level for this one answer; the kept level stays. */
export const REDO: Record<Level, { label: string; message: string }> = {
  steps: { label: 'Подробнее, по шагам', message: 'Объясни подробнее, по шагам.' },
  expert: { label: 'Короче', message: 'Короче: только значение, инструмент и страница.' },
}

export const otherLevel = (l: Level): Level => (l === 'expert' ? 'steps' : 'expert')

/** The same by voice or typed: «подробнее», «по шагам» → steps; «короче», «покороче», «коротко» → expert. */
export function redoLevel(message: string): Level | null {
  const m = message.trim().toLowerCase()
  if (/^(подробнее|по шагам|объясни подробнее)/.test(m)) return 'steps'
  if (/^(короче|покороче|коротко)/.test(m)) return 'expert'
  return null
}
