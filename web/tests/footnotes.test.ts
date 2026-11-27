// The compact answer: numbers of the pages, the list by document without repeats, «Коротко», the answer's
// own «Источники». Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { SourceItem } from '../src/api.ts'
import { parseAnswer } from '../src/lib/answer.ts'
import { citedHandles, footnotes, splitLead, withoutSources } from '../src/lib/footnotes.ts'

const src = (handle: string, manual_id: string, pdf_page: number): SourceItem => ({
  handle,
  manual_id,
  short: manual_id,
  designation: manual_id,
  pdf_page,
})
const SOURCES = {
  S1: src('S1', 're', 31),
  S2: src('S2', 'rk', 269),
  S3: src('S3', 're', 34),
  S4: src('S4', 're', 34), // the same page as S3 under another handle
  S5: src('S5', 'rk', 122),
}

test('a page gets one number, by its first citation; two handles of one page share it', () => {
  const { numberOf, docs } = footnotes(['S2', 'S1', 'S3', 'S2', 'S4', 'S5'], SOURCES)
  assert.deepEqual(Object.fromEntries(numberOf), { S2: 1, S1: 2, S3: 3, S4: 3, S5: 4 })
  // by document, in the order the answer first cites each; each page once
  assert.deepEqual(
    docs.map((d) => [d.manual_id, d.pages.map((p) => [p.n, p.source.pdf_page, p.handles])]),
    [
      [
        'rk',
        [
          [1, 269, ['S2']],
          [4, 122, ['S5']],
        ],
      ],
      [
        're',
        [
          [2, 31, ['S1']],
          [3, 34, ['S3', 'S4']],
        ],
      ],
    ],
  )
})

test('a handle the server never issued has no number and no page', () => {
  const { numberOf, docs } = footnotes(['S9', 'S1'], SOURCES)
  assert.deepEqual(Object.fromEntries(numberOf), { S1: 1 })
  assert.equal(docs.length, 1)
})

const ANSWER = [
  '**Регулировать на холодном двигателе [S1].**',
  'Что проверить',
  '1. Снять крышки [S2][S3].',
  '2. Установить зазор 0,25–0,30 мм [S3].',
  'Источники',
  '- РЭ, стр. 31 [S1]; РЭ, стр. 34 [S4]',
  'Ограничения',
  'Значение для другого двигателя не подходит [S5].',
].join('\n')

test('the cited handles are read in the order drawn, the «Источники» section too', () => {
  assert.deepEqual(citedHandles(parseAnswer(ANSWER)), ['S1', 'S2', 'S3', 'S3', 'S1', 'S4', 'S5'])
})

test('the answer’s own «Источники» is left out: the list of pages takes its place; the next section stays', () => {
  const titles = withoutSources(parseAnswer(ANSWER)).map((n) => (n.kind === 'section' ? n.title : n.kind))
  assert.deepEqual(titles, ['paragraph', 'Что проверить', 'ordered', 'Ограничения', 'paragraph'])
})

test('«Коротко» is the first paragraph; an answer of one block or one that starts otherwise is not split', () => {
  const { lead, rest } = splitLead(parseAnswer(ANSWER))
  assert.equal(lead?.kind, 'paragraph')
  assert.equal(rest.length, 6)
  assert.equal(splitLead(parseAnswer('Одна строка [S1].')).lead, null)
  assert.equal(splitLead(parseAnswer('Что проверить\n1. Шаг')).lead, null)
  assert.deepEqual(splitLead([]), { lead: null, rest: [] })
})
