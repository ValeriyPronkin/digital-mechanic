// The chief mechanic's register (#110): the totals, the filter by state and the confirmation by fault type
// are counted from the list of tickets. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { byFault, priorityChanged, shownTickets, ticketState, totals, type Counted } from '../src/lib/register.ts'

const TITLES: Record<string, string> = {
  F01: 'Клапанный механизм',
  F02: 'Низкое давление масла',
  F03: 'Перегрев, охлаждающая жидкость в масле',
}
const ticket = (id: number, code: string, outcome: Counted['outcome'] = null) => ({
  id,
  outcome,
  payload: { anomaly_type: code },
  fault_title: TITLES[code],
})

// newest first, as the server sends them: one waiting, one confirmed, one «другая неисправность»
const THREE = [ticket(3, 'F03', 'other_fault'), ticket(2, 'F02', 'confirmed'), ticket(1, 'F01')]

test('the totals: tickets, waiting for the inspection, confirmed of those with a result', () => {
  assert.deepEqual(totals(THREE), { tickets: 3, waiting: 1, recorded: 2, confirmed: 1 })
  assert.deepEqual(totals([]), { tickets: 0, waiting: 0, recorded: 0, confirmed: 0 })
  assert.deepEqual(totals([ticket(1, 'F01'), ticket(2, 'F01')]), { tickets: 2, waiting: 2, recorded: 0, confirmed: 0 })
  // «не подтвердилось» is a result too: it counts as recorded, not as confirmed
  assert.deepEqual(totals([ticket(1, 'F01', 'not_confirmed')]), { tickets: 1, waiting: 0, recorded: 1, confirmed: 0 })
})

test('a ticket without an outcome waits for the inspection; with one, its state is the outcome', () => {
  assert.deepEqual(THREE.map(ticketState), ['other_fault', 'confirmed', 'waiting'])
})

test('the filter keeps the order and splits the list in two with nothing left over', () => {
  assert.deepEqual(
    shownTickets(THREE, 'all').map((t) => t.id),
    [3, 2, 1],
  )
  assert.deepEqual(
    shownTickets(THREE, 'waiting').map((t) => t.id),
    [1],
  )
  assert.deepEqual(
    shownTickets(THREE, 'recorded').map((t) => t.id),
    [3, 2],
  )
  const t = totals(THREE)
  assert.equal(shownTickets(THREE, 'waiting').length, t.waiting)
  assert.equal(shownTickets(THREE, 'recorded').length, t.recorded)
  assert.deepEqual(shownTickets([], 'recorded'), [])
})

test('by fault type: only faults with a result, each with its tickets and confirmed of recorded', () => {
  assert.deepEqual(byFault(THREE), [
    { code: 'F02', title: TITLES.F02, tickets: 1, recorded: 1, confirmed: 1, otherFault: 0 },
    { code: 'F03', title: TITLES.F03, tickets: 1, recorded: 1, confirmed: 0, otherFault: 1 },
  ])
  // F01 has a ticket and no result: it is not listed as «0 из 0»
  assert.equal(
    byFault(THREE).some((f) => f.code === 'F01'),
    false,
  )
  assert.deepEqual(byFault([ticket(1, 'F01'), ticket(2, 'F02')]), [])
})

test('by fault type: tickets that wait count as tickets of the fault, and the fault with more results is first', () => {
  const list = [
    ticket(6, 'F01', 'confirmed'),
    ticket(5, 'F01', 'not_confirmed'),
    ticket(4, 'F01'),
    ticket(3, 'F01', 'confirmed'),
    ticket(2, 'F03', 'confirmed'),
    ticket(1, 'F02', 'other_fault'),
  ]
  assert.deepEqual(byFault(list), [
    { code: 'F01', title: TITLES.F01, tickets: 4, recorded: 3, confirmed: 2, otherFault: 0 },
    { code: 'F02', title: TITLES.F02, tickets: 1, recorded: 1, confirmed: 0, otherFault: 1 },
    { code: 'F03', title: TITLES.F03, tickets: 1, recorded: 1, confirmed: 1, otherFault: 0 },
  ])
  // the sums over the faults are the totals when every fault has a result
  const t = totals(list)
  const sum = (key: 'tickets' | 'recorded' | 'confirmed') => byFault(list).reduce((n, f) => n + f[key], 0)
  assert.deepEqual([sum('tickets'), sum('recorded'), sum('confirmed')], [t.tickets, t.recorded, t.confirmed])
})

test('by fault type: «другая неисправность» is counted apart from «не подтвердилось»', () => {
  // three tickets of one fault: confirmed, a false alarm, a real fault of another kind
  const list = [ticket(3, 'F02', 'confirmed'), ticket(2, 'F02', 'not_confirmed'), ticket(1, 'F02', 'other_fault')]
  const [fault] = byFault(list)
  assert.deepEqual(fault, { code: 'F02', title: TITLES.F02, tickets: 3, recorded: 3, confirmed: 1, otherFault: 1 })
  // what is left of the recorded is the false alarms
  assert.equal(fault.recorded - fault.confirmed - fault.otherFault, 1)
  // a false alarm alone leaves the third number at zero: the line does not show it
  assert.equal(byFault([ticket(1, 'F01', 'not_confirmed')])[0].otherFault, 0)
})

test('the priority is shown as changed only when the ticket carries another proposal', () => {
  assert.equal(priorityChanged({ payload: { urgency: 'medium' }, urgency_proposed: 'high' }), true)
  assert.equal(priorityChanged({ payload: { urgency: 'high' }, urgency_proposed: 'high' }), false)
  assert.equal(priorityChanged({ payload: { urgency: 'high' }, urgency_proposed: null }), false)
  assert.equal(priorityChanged({ payload: { urgency: 'high' } }), false)
})
