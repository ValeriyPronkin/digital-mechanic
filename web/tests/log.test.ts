// The action log (#73): what a step is shown to have asked for, and the numbers of the closed row.
// Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { SourceItem, UsageEvent } from '../src/api.ts'
import { logTotals, stepDetail } from '../src/lib/log.ts'

const NBSP = '\u00a0'
const source = (handle: string, pdf_page: number): SourceItem => ({
  handle,
  manual_id: 'yamz-236-rk',
  short: '236.01.01 РК',
  chip: '236.01.01 РК',
  designation: '236.01.01 РК',
  pdf_page,
})
const SOURCES = [source('S1', 41), source('S2', 139)]
const NAMES = { 'yamz-236-rk': '236.01.01 РК', 'yamz-236-re': '236-3902150-Б РЭ' }
const read = (input: Record<string, unknown>, sources = SOURCES) => {
  const { chips, text } = stepDetail(input, sources, NAMES)
  return { chips: chips.map((s) => s.handle), text }
}

test('pages the agent read are chips, in the order it asked for them', () => {
  for (const manual of ['yamz-236-rk', '236.01.01 РК', ' 236.01.01 РК '])
    assert.deepEqual(read({ manual, pages: [139, 41, '41'] }), { chips: ['S2', 'S1'], text: null })
})

test('a page the agent asked for and did not get is said in words, never as a chip', () => {
  assert.deepEqual(read({ manual: 'yamz-236-rk', pages: [41, 999] }), {
    chips: ['S1'],
    text: `запрошено: 236.01.01 РК, стр.${NBSP}999`,
  })
  // Nothing was issued for this manual in the thread: the name comes from the vehicle's manuals.
  assert.deepEqual(read({ manual: 'yamz-236-re', pages: [19] }), {
    chips: [],
    text: `запрошено: 236-3902150-Б РЭ, стр.${NBSP}19`,
  })
  assert.deepEqual(read({ manual: 'yamz-236-rk', pages: [41] }, []), {
    chips: [],
    text: `запрошено: 236.01.01 РК, стр.${NBSP}41`,
  })
})

test('a manual that does not resolve is shown as the request it was, with only the pages that parse', () => {
  const bad = read({ manual: 'Руководство, которого нет', pages: ['сорок', NaN, 77, '78', -1, 0, 1.5, null, {}] })
  assert.deepEqual(bad, { chips: [], text: `запрошено: «Руководство, которого нет», стр.${NBSP}77, 78` })
  for (const input of [
    { manual: 'Руководство, которого нет', pages: ['сорок', NaN] },
    { manual: 'Руководство, которого нет', pages: 'все' },
    { manual: 'Руководство, которого нет' },
  ])
    assert.deepEqual(read(input), { chips: [], text: 'запрошено: «Руководство, которого нет»' })
  assert.deepEqual(read({ pages: [5] }), { chips: [], text: `запрошено: стр.${NBSP}5` }) // no manual named
  assert.deepEqual(read({ manual: 42, pages: ['x'] }), { chips: [], text: null }) // nothing parses: nothing shown
  assert.deepEqual(read({ manual: '', pages: [] }), { chips: [], text: null })
})

test('a manual named like a method of an object is a name, not a function printed in the log', () => {
  for (const manual of ['toString', 'constructor', 'hasOwnProperty', '__proto__', 'valueOf'])
    assert.deepEqual(read({ manual, pages: [41] }), { chips: [], text: `запрошено: «${manual}», стр.${NBSP}41` })
})

test('a page is a safe positive whole number: nothing is printed in exponent form', () => {
  const huge = read({ manual: 'yamz-236-rk', pages: [1e21, '1000000000000000000000', 2 ** 53, Infinity, 41, 999] })
  assert.deepEqual(huge, { chips: ['S1'], text: `запрошено: 236.01.01 РК, стр.${NBSP}999` })
  assert.deepEqual(read({ manual: 'yamz-236-rk', pages: [1e21, '9007199254740993', -5, 0] }), {
    chips: [],
    text: 'запрошено: 236.01.01 РК',
  })
  for (const pages of [[1e21], [1.5e300], ['1e5'], [Number.MAX_VALUE]])
    assert.doesNotMatch(read({ manual: 'yamz-236-rk', pages }).text ?? '', /e\+|\de\d|Infinity/)
})

test('the log never prints «NaN», «undefined» or «null»', () => {
  const inputs: Record<string, unknown>[] = [
    { manual: 'yamz-236-rk', pages: [NaN, 'NaN', undefined, null, 41] },
    { manual: undefined, pages: [NaN] },
    { manual: null, pages: null },
    { query: null },
    { session_id: undefined },
    { operations: 'нет' },
    {},
  ]
  for (const input of inputs) {
    const { text } = stepDetail(input, SOURCES, NAMES)
    if (text !== null) assert.doesNotMatch(text, /NaN|undefined|null/)
  }
  assert.deepEqual(stepDetail(undefined, SOURCES, NAMES), { chips: [], text: null })
})

test('the other steps: the query in quotes, the check, the number of works', () => {
  assert.equal(read({ query: ' момент затяжки ' }).text, '«момент затяжки»')
  assert.equal(read({ query: '   ' }).text, null)
  assert.equal(read({ session_id: 'S-0042' }).text, 'S-0042')
  assert.equal(read({ operations: ['a', 'b', 'c'], spare_parts: [] }).text, 'работ в заявке: 3')
  assert.equal(read({}).text, null) // a step with no arguments shows its name only
})

const usage = (cost_rub: number, tokens: number): UsageEvent => ({
  model: 'anthropic/claude-sonnet-5.5',
  input_tokens: tokens,
  cache_write_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: 0,
  latency_ms: 100,
  cost_usd: cost_rub / 81,
  cost_rub,
  replayed: cost_rub === 0,
})

test('the closed row: steps declined by number and the cost; a turn that cost nothing shows no «0,00 ₽»', () => {
  assert.equal(
    logTotals(3, [usage(0.5, 10000), usage(0.42, 10932)]).closed,
    `Журнал действий · 3${NBSP}шага · 0,92${NBSP}₽`,
  )
  assert.equal(logTotals(1, [usage(1.15, 22640)]).closed, `Журнал действий · 1${NBSP}шаг · 1,15${NBSP}₽`)
  assert.equal(logTotals(5, [usage(0.004, 12140)]).closed, `Журнал действий · 5${NBSP}шагов`) // rounds to 0,00
  assert.equal(logTotals(4, [usage(0, 12140)]).closed, `Журнал действий · 4${NBSP}шага`) // a replayed turn
  assert.equal(logTotals(0, [usage(0.31, 5000)]).closed, `Журнал действий · 0,31${NBSP}₽`) // answered without a tool
  assert.equal(logTotals(2, []).closed, `Журнал действий · 2${NBSP}шага`) // the model was unavailable
})

test('inside the log: the cost on its own line when there is one, then the calls, the tokens and the model', () => {
  const paid = logTotals(3, [usage(0.5, 10000), usage(0.42, 10932)])
  assert.equal(paid.price, `0,92${NBSP}₽`)
  assert.match(paid.calls ?? '', /^2 обращения к модели · 20\s932 токена · claude-sonnet-5\.5$/)
  const free = logTotals(4, [usage(0, 12140)])
  assert.equal(free.price, null)
  assert.match(free.calls ?? '', /^1 обращение к модели · 12\s140 токенов · claude-sonnet-5\.5$/)
  assert.deepEqual(logTotals(2, []), { closed: `Журнал действий · 2${NBSP}шага`, price: null, calls: null })
})
