// The vehicle's conversation history (#92): Moscow time, status words, the open one marked. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { ThreadRow } from '../src/api.ts'
import { historyRows, moscowTime } from '../src/lib/history.ts'

const NBSP = ' '
const row = (over: Partial<ThreadRow> = {}): ThreadRow => ({
  thread_id: 'a1b2',
  started_at: '2026-11-27T08:40:00+00:00',
  updated_at: '2026-11-27T21:05:00+00:00',
  session_id: 'S-0009',
  topic: 'Какой зазор клапанов?',
  status: 'open',
  ticket_id: null,
  records: 2,
  ...over,
})

test('UTC is shown in Moscow time, across midnight too', () => {
  assert.equal(moscowTime('2026-11-27T08:40:00+00:00'), `27${NBSP}ноя, 11:40`)
  assert.equal(moscowTime('2026-11-27T21:05:00+00:00'), `28${NBSP}ноя, 00:05`)
  assert.equal(moscowTime(null), '')
  assert.equal(moscowTime('не дата'), '')
})

test('a row: last change time, topic, status word, records; the open one is marked', () => {
  const [r] = historyRows([row()], 'a1b2')
  assert.deepEqual(r, {
    id: 'a1b2',
    when: `28${NBSP}ноя, 00:05`,
    topic: 'Какой зазор клапанов?',
    status: 'разговор',
    ticket: null,
    records: 'записей: 2',
    current: true,
    canClaim: true,
  })
})

test('a sent ticket, no topic, no records: no export offered', () => {
  const [r] = historyRows([row({ status: 'ticket_sent', ticket_id: 'TKT-0007', topic: ' ', records: 0 })], 'other')
  assert.equal(r.status, 'заявка отправлена')
  assert.equal(r.ticket, 'TKT-0007')
  assert.equal(r.topic, 'без вопроса')
  assert.equal(r.current, false)
  assert.equal(r.canClaim, false)
})

test('an unknown status is shown as the server sent it', () => {
  assert.equal(historyRows([row({ status: 'archived' })], null)[0].status, 'archived')
})
