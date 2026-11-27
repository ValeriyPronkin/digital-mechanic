// What the chief mechanic's register counts over the list of tickets: the totals, the filter by state and
// the confirmation by fault type (web/tests/register.test.ts). The list comes from `GET /api/v2/tickets`.
// Ported from Nikita's interface (lib/register.ts).
/** Which tickets the register shows: all, those that wait for the defect inspection, those with a result. */
export type RegisterFilter = 'all' | 'waiting' | 'recorded'

/** What a ticket must carry to be counted. */
export interface Counted {
  outcome: 'confirmed' | 'not_confirmed' | 'other_fault' | null
  payload: { anomaly_type: string }
  fault_title: string
}

/** What came of a ticket: the outcome of the defect inspection, or `waiting` until one is recorded. */
export type TicketState = 'waiting' | NonNullable<Counted['outcome']>
export const ticketState = (ticket: Pick<Counted, 'outcome'>): TicketState => ticket.outcome ?? 'waiting'

export interface Totals {
  tickets: number
  waiting: number // no outcome recorded yet
  recorded: number // with an outcome
  confirmed: number // of the recorded, the inspection confirmed the check
}

export function totals(tickets: readonly Pick<Counted, 'outcome'>[]): Totals {
  const recorded = tickets.filter((t) => t.outcome !== null).length
  return {
    tickets: tickets.length,
    waiting: tickets.length - recorded,
    recorded,
    confirmed: tickets.filter((t) => t.outcome === 'confirmed').length,
  }
}

/** The tickets a filter leaves, in the order they came. */
export function shownTickets<T extends Pick<Counted, 'outcome'>>(tickets: readonly T[], show: RegisterFilter): T[] {
  if (show === 'all') return [...tickets]
  return tickets.filter((t) => (t.outcome === null) === (show === 'waiting'))
}

export interface FaultCount {
  code: string // `anomaly_type`
  title: string
  tickets: number
  recorded: number
  confirmed: number
  /** Of the recorded, «другая неисправность»: a real fault of another kind. For the owners of the acoustic
   *  model this is not the error «не подтвердилось» is (a false alarm, `recorded - confirmed - otherFault`):
   *  the check was right to raise the vehicle and wrong about the class. */
  otherFault: number
}

/** How often the inspection confirmed the check, by fault type.
 *
 *  Only a fault with at least one recorded outcome is listed: «подтвердилось 0 из 0» says nothing, and a
 *  fault whose tickets all wait is in the list of tickets already. The fault with the most outcomes comes
 *  first, then by name, so the order does not depend on which ticket is the newest. */
export function byFault(tickets: readonly Counted[]): FaultCount[] {
  const faults = new Map<string, FaultCount>()
  for (const t of tickets) {
    const code = t.payload.anomaly_type
    const fault = faults.get(code) ?? {
      code,
      title: t.fault_title,
      tickets: 0,
      recorded: 0,
      confirmed: 0,
      otherFault: 0,
    }
    fault.tickets += 1
    if (t.outcome !== null) fault.recorded += 1
    if (t.outcome === 'confirmed') fault.confirmed += 1
    if (t.outcome === 'other_fault') fault.otherFault += 1
    faults.set(code, fault)
  }
  return [...faults.values()]
    .filter((f) => f.recorded > 0)
    .sort((a, b) => b.recorded - a.recorded || a.title.localeCompare(b.title, 'ru'))
}

/** The priority the ticket went with is not the one the server proposed: the mechanic chose another.
 *  A ticket stored before the choice existed carries no proposal and went with the proposed one. */
export function priorityChanged(ticket: { payload: { urgency: string }; urgency_proposed?: string | null }): boolean {
  return ticket.urgency_proposed != null && ticket.urgency_proposed !== ticket.payload.urgency
}
