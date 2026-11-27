// The chief mechanic's queue of contradictions (#93): routes, counters, the letter that goes to the server,
// the time by Moscow. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  editedText,
  firstStatus,
  knownEvents,
  moscowTime,
  queueCounts,
  queueHref,
  queueRoute,
  shownItems,
} from '../src/lib/contradictions.ts'

test('a hash of the queue: the list, an item by its number, the journal; anything else is not the queue', () => {
  assert.deepEqual(queueRoute('contradictions'), { view: 'list' })
  assert.deepEqual(queueRoute('contradictions/'), { view: 'list' })
  assert.deepEqual(queueRoute('contradictions/3'), { view: 'item', number: 3 })
  assert.deepEqual(queueRoute('contradictions/journal'), { view: 'journal' })
  // a number the queue cannot have goes to the list, not to an empty item
  assert.deepEqual(queueRoute('contradictions/0'), { view: 'list' })
  assert.deepEqual(queueRoute('contradictions/abc'), { view: 'list' })
  assert.equal(queueRoute('contradictions/3/x'), null)
  assert.equal(queueRoute('tickets'), null)
  assert.equal(queueRoute('B418HK98'), null)
  assert.equal(queueRoute(null), null)
})

test('the links are the routes read back', () => {
  for (const r of [{ view: 'list' }, { view: 'item', number: 12 }, { view: 'journal' }] as const)
    assert.deepEqual(queueRoute(queueHref(r).slice(2)), r)
})

const ITEMS = [
  { number: 2, status: 'open' as const },
  { number: 1, status: 'resolved' as const },
  { number: 3, status: 'open' as const },
  { number: 4, status: 'sent' as const },
]

test('the counters count by status; a filter keeps the order the server sent', () => {
  assert.deepEqual(queueCounts(ITEMS), { open: 2, sent: 1, resolved: 1 })
  assert.deepEqual(queueCounts([]), { open: 0, sent: 0, resolved: 0 })
  assert.deepEqual(
    shownItems(ITEMS, 'open').map((i) => i.number),
    [2, 3],
  )
})

test('the queue opens on the first status with something in it', () => {
  assert.equal(firstStatus({ open: 1, sent: 2, resolved: 0 }), 'open')
  assert.equal(firstStatus({ open: 0, sent: 2, resolved: 1 }), 'sent')
  assert.equal(firstStatus({ open: 0, sent: 0, resolved: 1 }), 'resolved')
  assert.equal(firstStatus({ open: 0, sent: 0, resolved: 0 }), 'open')
})

test('the letter goes to the server only when the chief mechanic changed it', () => {
  const draft = 'Кому: завод-изготовитель\n\nЗдравствуйте.'
  assert.equal(editedText(draft, draft), undefined)
  assert.equal(editedText(draft, `${draft}\n`), undefined) // a line break at the end is not an edit
  assert.equal(editedText(draft, '   '), undefined) // an emptied field: the server's draft
  assert.equal(editedText(draft, `${draft}\nСрочно.`), `${draft}\nСрочно.`)
})

test('the time is Moscow time, whatever the zone of the phone', () => {
  assert.equal(moscowTime('2026-11-27T08:40:00+00:00'), '27 ноября, 11:40')
  assert.equal(moscowTime('2026-11-27T22:05:00+00:00'), '28 ноября, 01:05')
  assert.equal(moscowTime('не дата'), 'не дата')
})

test('the journal skips an event it does not know instead of showing it as a decision', () => {
  const base = { number: 1, id: 'x', seq: 1, at: '2026-11-27T08:40:00+00:00', by: 'Главный механик' }
  const events = [
    { ...base, event: 'sent', to: 'manufacturer', text: 'т', channel: 'none' },
    { ...base, seq: 2, event: 'reopened' },
    { ...base, seq: 3, event: 'resolved', text: 'р', source: 'support', document: null },
  ]
  assert.deepEqual(
    knownEvents(events).map((e) => e.seq),
    [1, 3],
  )
})
