// How a fleet row lays out the server's reason line and where the outcomes row goes in the list
// (web/tests/fleet.test.ts).

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
