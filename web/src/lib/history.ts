import type { ThreadRow } from '../api.ts'
import { copy } from '../copy.ts'

const NBSP = ' '
const MONTHS_SHORT = 'янв фев мар апр мая июн июл авг сен окт ноя дек'.split(' ')
const MOSCOW_MS = 3 * 3600 * 1000 // UTC+3 all year

/** «27 ноя, 14:40» по Москве: время истории сервер пишет в UTC, механик и жюри читают московское. */
export function moscowTime(iso: string | null): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const d = new Date(t + MOSCOW_MS)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCDate()}${NBSP}${MONTHS_SHORT[d.getUTCMonth()]}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

export interface HistoryRow {
  id: string
  when: string
  topic: string
  status: string
  ticket: string | null
  records: string
  current: boolean
  canClaim: boolean // a record exists: the warranty-claim export has something to show
}

/** The history list as shown: newest first (as the server sends it), the open conversation marked. */
export function historyRows(rows: ThreadRow[], currentId: string | null): HistoryRow[] {
  return rows.map((r) => ({
    id: r.thread_id,
    when: moscowTime(r.updated_at ?? r.started_at),
    topic: (r.topic ?? '').trim() || copy.history.noTopic,
    status: copy.history.status[r.status] ?? r.status,
    ticket: r.ticket_id,
    records: copy.history.records(r.records ?? 0),
    current: r.thread_id === currentId,
    canClaim: (r.records ?? 0) > 0,
  }))
}
