// How a fleet row lays out the server's reason line and where the outcomes row goes in the list
// (web/tests/fleet.test.ts).
import type { FleetStatusView } from '../api.ts'
import { copy } from '../copy.ts' // named in full: web/tests load this module in Node
import { num } from './format.ts'

const SEPARATOR = ' · '
const NBSP = ' '

/** The reason line of a fleet row, cut into the pieces it may be wrapped between.
 *
 *  The server writes it as facts joined by « · »: «Клапанный механизм · оценка 0,93 · приоритет высокий».
 *  Whether it fits one line depends on the phone and its font, so the row does not count pixels: it lets the
 *  line break only between facts. Each piece but the last carries its separator, tied to it by a
 *  non-breaking space, so a line never starts with «·» and never ends with a lone «оценка» or begins with a
 *  lone «высокий». The first piece, the name of the fault, may still wrap inside itself; the others are
 *  drawn without a break (`whitespace-nowrap` in the row). A line without separators is one piece. */
export function reasonParts(reason: string): string[] {
  const facts = reason.split(SEPARATOR)
  return facts.map((fact, i) => (i < facts.length - 1 ? `${fact}${NBSP}·` : fact))
}

/** The reason line of a fleet row: the fault, its score and the priority, «Клапанный механизм · оценка 0,93 ·
 *  приоритет высокий». Built from the fields of the status, not from `reason`: the server writes that one as
 *  the trace of its rule («F01 «Клапанный механизм»: Клапанный механизм — класс 2 из 3; оценка 0,93 — не ниже
 *  порога 0,85 → высокая»), which names the fault twice and reads as a log in a list. The trace stays where it
 *  explains the priority: on the vehicle's card. Without a fault (a failed recording) the server's line is
 *  what there is to say. */
export function reasonLine(f: Pick<FleetStatusView, 'fault_title' | 'anomaly_score' | 'urgency' | 'reason'>): string {
  if (!f.fault_title) return f.reason
  const facts = [f.fault_title]
  if (f.anomaly_score !== null) facts.push(`${copy.fleet.score} ${num(f.anomaly_score)}`)
  if (f.urgency) facts.push(`${copy.fleet.priority} ${copy.urgency[f.urgency]}`)
  return facts.join(SEPARATOR)
}

/** How many vehicles of the unfiltered list stand before the outcomes row. */
export const VEHICLES_BEFORE_OUTCOMES = 3

/** Where the outcomes row goes in the list of vehicles on screen: the index of the vehicle it is drawn
 *  before, `shown` when it closes the list, `null` when it is left out.
 *
 *  The row is about the whole fleet, not about the vehicles on screen. In the full list it has one place on
 *  every phone: after the three vehicles to deal with first (after the last one when the fleet has fewer),
 *  so three stay above the fold at 320×568 and the row is one short scroll away. Under a search or a status
 *  filter the vehicles on screen are an answer to a question, and a row in the middle of them reads as one
 *  of the matches: it goes after the last match. With no match there is no list to close, and the row is not
 *  left alone under «Такой машины в парке нет». */
export function outcomesPlace(shown: number, filtered: boolean): number | null {
  if (shown === 0) return null
  return filtered ? shown : Math.min(shown, VEHICLES_BEFORE_OUTCOMES)
}
