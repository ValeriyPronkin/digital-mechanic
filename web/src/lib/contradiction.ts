import type { ContradictionBlock } from '../api.ts'
import { copy } from '../copy.ts'

/** What the contradiction card says under the wordings about the hand-over to the chief mechanic (#93).
 *  `open`: «№ N · у главного механика» and the safe rule until a decision; `resolved`: «№ N · решено» and the
 *  decision with its source and date, drawn in the colour of a settled thing, beside the wordings (not instead
 *  of them). Null for a block without `escalation` (threads before #93): nothing is shown. */
export type EscalationView = { tone: 'open' | 'resolved'; badge: string; line: string; number: number | null }

export function escalationView(block: ContradictionBlock): EscalationView | null {
  const e = block.escalation
  if (!e) return null
  const line = (e.line || block.advice || '').trim()
  const n = e.number ?? null
  return e.resolved
    ? { tone: 'resolved', badge: copy.contradiction.resolved(n), line, number: n }
    : { tone: 'open', badge: copy.contradiction.open(n), line, number: n }
}
