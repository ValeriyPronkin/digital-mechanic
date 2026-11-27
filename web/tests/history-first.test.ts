// «Обращения по машине»: the newest three, the open one always, then «Показать все». Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { firstRows } from '../src/lib/history.ts'

const rows = (n: number, current = -1) => Array.from({ length: n }, (_, i) => ({ id: i, current: i === current }))

test('the newest three; fewer when there are fewer', () => {
  assert.deepEqual(
    firstRows(rows(7)).map((r) => r.id),
    [0, 1, 2],
  )
  assert.deepEqual(
    firstRows(rows(2)).map((r) => r.id),
    [0, 1],
  )
})

test('the open conversation is in the list even when it is older than the three', () => {
  assert.deepEqual(
    firstRows(rows(7, 5)).map((r) => r.id),
    [0, 1, 2, 5],
  )
  assert.deepEqual(
    firstRows(rows(7, 1)).map((r) => r.id),
    [0, 1, 2],
  )
})
