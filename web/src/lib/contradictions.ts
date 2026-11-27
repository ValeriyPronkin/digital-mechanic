// The chief mechanic's queue of contradictions between manuals (#93, docs/api-v2-web.md §6): where a route
// points, what the counters count, what the journal says, when the edited letter goes to the server.
// Tested in web/tests/contradictions.test.ts.
import type { ContradictionEvent, ContradictionItem, ContradictionStatus } from '../api.ts'

/** The address of the queue: `#/contradictions`, an item `#/contradictions/3`, the journal `#/contradictions/journal`. */
export const CONTRADICTIONS = 'contradictions'

export type QueueRoute = { view: 'list' } | { view: 'item'; number: number } | { view: 'journal' }

/** What a hash of the app shows, if it is the queue's: null for a vehicle or the register. */
export function queueRoute(selected: string | null): QueueRoute | null {
  if (!selected) return null
  const [head, rest, ...more] = selected.split('/')
  if (head !== CONTRADICTIONS || more.length > 0) return null
  if (rest === undefined || rest === '') return { view: 'list' }
  if (rest === 'journal') return { view: 'journal' }
  return /^[1-9]\d*$/.test(rest) ? { view: 'item', number: Number(rest) } : { view: 'list' }
}

export const queueHref = (route: QueueRoute) =>
  `#/${CONTRADICTIONS}` + (route.view === 'item' ? `/${route.number}` : route.view === 'journal' ? '/journal' : '')

export const STATUSES: ContradictionStatus[] = ['open', 'sent', 'resolved']

export function queueCounts(items: readonly Pick<ContradictionItem, 'status'>[]): Record<ContradictionStatus, number> {
  const counts = { open: 0, sent: 0, resolved: 0 }
  for (const i of items) if (i.status in counts) counts[i.status] += 1
  return counts
}

/** The items of one status, in the order the server sent them (most frequent first). */
export const shownItems = <T extends Pick<ContradictionItem, 'status'>>(
  items: readonly T[],
  status: ContradictionStatus,
) => items.filter((i) => i.status === status)

/** The counter that opens first: the first one with something in it, open before sent before resolved. */
export const firstStatus = (counts: Record<ContradictionStatus, number>): ContradictionStatus =>
  STATUSES.find((s) => counts[s] > 0) ?? 'open'

/** The edited letter goes to the server only when it differs from the draft: otherwise the server keeps its own
 *  text, built for the addressee. An emptied field is not a letter either. */
export function editedText(draft: string, text: string): string | undefined {
  const t = text.trim()
  return t === '' || t === draft.trim() ? undefined : text
}

const MSK = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: 'numeric',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
})

/** «27 ноября, 11:40» by Moscow time: the server writes UTC, the depot reads Moscow time. */
export function moscowTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = Object.fromEntries(MSK.formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.day} ${p.month}, ${p.hour}:${p.minute}`
}

/** The journal lines the screen knows how to say: `sent` and `resolved`. A new kind of event may come before
 *  the screen learns it, and it is skipped, not shown as a decision. */
export const knownEvents = (events: readonly { event?: unknown }[]): ContradictionEvent[] =>
  events.filter((e): e is ContradictionEvent => e.event === 'sent' || e.event === 'resolved')
