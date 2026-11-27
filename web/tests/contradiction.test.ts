// The hand-over line of the contradiction card (#93): number, open or decided. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { ContradictionBlock } from '../src/api.ts'
import { escalationView } from '../src/lib/contradiction.ts'

const base: ContradictionBlock = {
  kind: 'contradiction',
  title: 'когда регулировать зазоры',
  items: [],
  conclusion: 'Вывод: регулировать на холодном двигателе.',
  advice: 'Передано главному механику на решение (№ 3). Пока — безопасное правило: по выводу выше.',
}

test('no escalation (a thread before #93): nothing under the wordings', () => {
  assert.equal(escalationView(base), null)
  assert.equal(escalationView({ ...base, escalation: null }), null)
})

test('open: number for the chief mechanic and the safe rule', () => {
  const v = escalationView({ ...base, escalation: { line: base.advice, number: 3, resolved: false } })
  assert.deepEqual(v, { tone: 'open', badge: '№ 3 · у главного механика', line: base.advice, number: 3 })
})

test('resolved: the decision with its source and date, not the safe rule', () => {
  const line = 'Решение по противоречию (источник: завод-изготовитель, 27.11.2026): на холодном двигателе.'
  const v = escalationView({ ...base, advice: line, escalation: { line, number: 3, resolved: true } })
  assert.equal(v?.tone, 'resolved')
  assert.equal(v?.badge, '№ 3 · решено')
  assert.equal(v?.line, line)
})

test('an empty line falls back to the advice the server sent', () => {
  const v = escalationView({ ...base, escalation: { line: '', number: 7, resolved: false } })
  assert.equal(v?.line, base.advice)
})

test('a decided line without a number (older server): «Решено», never «№ null»', () => {
  const v = escalationView({
    ...base,
    escalation: { line: 'Решение по противоречию (…)', number: null, resolved: true },
  })
  assert.equal(v?.badge, 'Решено')
  assert.equal(v?.number, null)
})
