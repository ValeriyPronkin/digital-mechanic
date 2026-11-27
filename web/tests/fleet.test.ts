// The reason line of a fleet row breaks only between its facts, and the outcomes row has its place in the
// list (#83). Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { outcomesPlace, reasonLine, reasonParts } from '../src/lib/fleet.ts'

const NBSP = ' '

test('the reason line is cut between its facts, and each separator stays with the fact before it', () => {
  assert.deepEqual(reasonParts('Клапанный механизм · оценка 0,93 · приоритет высокий'), [
    `Клапанный механизм${NBSP}·`,
    `оценка 0,93${NBSP}·`,
    'приоритет высокий',
  ])
  // the mechanic's choice is part of the last fact: it is not torn from the priority
  assert.equal(
    reasonParts('Низкое давление масла · оценка 0,85 · приоритет средний, выбран механиком').at(-1),
    'приоритет средний, выбран механиком',
  )
})

test('joined by spaces the pieces read as the server wrote the line', () => {
  for (const reason of [
    'Перегрев, охлаждающая жидкость в масле · оценка 0,92 · приоритет высокий',
    'Отклонений не найдено · оценка 0,12',
    'Пригодных записей нет',
  ]) {
    assert.equal(reasonParts(reason).join(' ').replaceAll(NBSP, ' '), reason)
  }
})

test('a line without separators is one piece and wraps as any text', () => {
  assert.deepEqual(reasonParts('Пригодных записей нет'), ['Пригодных записей нет'])
  assert.deepEqual(reasonParts(''), [''])
})

test('in the full list the outcomes row goes after the third vehicle', () => {
  assert.equal(outcomesPlace(50, false), 3)
  assert.equal(outcomesPlace(4, false), 3)
  assert.equal(outcomesPlace(3, false), 3)
})

test('a full list of fewer than three vehicles is closed by the outcomes row', () => {
  assert.equal(outcomesPlace(2, false), 2)
  assert.equal(outcomesPlace(1, false), 1)
})

test('under a search or a status filter the outcomes row goes after the last match', () => {
  assert.equal(outcomesPlace(1, true), 1)
  assert.equal(outcomesPlace(5, true), 5)
})

test('with no match the outcomes row is left out', () => {
  assert.equal(outcomesPlace(0, true), null)
  assert.equal(outcomesPlace(0, false), null)
})

test('a row names the fault once, with its score and priority, not the trace of the rule', () => {
  const fleet = {
    fault_title: 'Перегрев, охлаждающая жидкость в масле',
    anomaly_score: 0.92,
    urgency: 'high' as const,
    reason:
      'F03 «Перегрев, охлаждающая жидкость в масле»: Перегрев, охлаждающая жидкость в масле — класс 3 из 3 → высокая',
  }
  assert.equal(reasonLine(fleet), 'Перегрев, охлаждающая жидкость в масле · оценка 0,92 · приоритет высокий')
  assert.equal(
    reasonLine({ ...fleet, fault_title: 'Генератор', anomaly_score: 0.83, urgency: 'low' }),
    'Генератор · оценка 0,83 · приоритет низкий',
  )
  // a failed recording has no fault: the server's line is what there is to say
  const failed = 'последняя проверка не удалась — выводов о двигателе нет'
  assert.equal(reasonLine({ fault_title: null, anomaly_score: null, urgency: null, reason: failed }), failed)
  // nothing to say for a vehicle in norm
  assert.equal(reasonLine({ fault_title: null, anomaly_score: 0.2, urgency: null, reason: '' }), '')
})
