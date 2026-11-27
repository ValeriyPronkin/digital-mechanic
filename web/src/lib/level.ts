/** The mechanic's level (#91, docs/api-v2-web.md §2). The server picks it for each question anew («auto»):
 *  nothing is kept on the device, because shifts change and a phone passes from hand to hand. Under the last
 *  answer «Подробнее» asks the same again one level down, toward the novice, and «Короче» one level up. */
export type Level = 'novice' | 'mechanic' | 'master'
export type LevelChoice = Level | 'auto'

const ORDER: readonly Level[] = ['novice', 'mechanic', 'master']

/** The level an answer was given at, as the server wrote it (`level_used` of the text event, or the
 *  passport's `question.level`). «steps» and «expert» are the names of the first two-level version (#17). */
export function levelOf(value: unknown): Level | null {
  if (value === 'novice' || value === 'mechanic' || value === 'master') return value
  if (value === 'steps') return 'novice'
  if (value === 'expert') return 'master'
  return null
}

/** «Подробнее»: one level down; null when the answer is already for a novice. */
export const moreDetail = (l: Level): Level | null => ORDER[ORDER.indexOf(l) - 1] ?? null
/** «Короче»: one level up; null when the answer is already for a master. */
export const shorter = (l: Level): Level | null => ORDER[ORDER.indexOf(l) + 1] ?? null

/** The same by voice or typed: «подробнее», «по шагам» go a level down from the last answer, «короче»,
 *  «покороче», «коротко» a level up. Without a last answer, to the end itself. Any other question: null,
 *  and the server picks. */
export function redoLevel(message: string, last: Level | null): Level | null {
  const m = message.trim().toLowerCase()
  if (/^(подробнее|по шагам|объясни подробнее)/.test(m)) return last ? moreDetail(last) : 'novice'
  if (/^(короче|покороче|коротко)/.test(m)) return last ? shorter(last) : 'master'
  return null
}
