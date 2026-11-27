// Parts and tools in the answer (docs/api-v2-web.md §8): which words get a colour. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { AnswerSpan } from '../src/api.ts'
import { markPieces, spanHint, usableSpans } from '../src/lib/spans.ts'

const span = (type: string, text: string, extra: Partial<AnswerSpan> = {}): AnswerSpan =>
  ({
    type,
    text,
    start: 0,
    end: 0,
    name: text,
    designation: null,
    page: null,
    manual_id: null,
    ref: null,
    ...extra,
  }) as AnswerSpan

const marked = (pieces: ReturnType<typeof markPieces>) =>
  pieces.map((line) => line.map((p) => (p.span ? `[${p.span.type}:${p.text}]` : p.text)).join(''))

test('the marked words get their kind; the text around them stays as it is', () => {
  const text = 'Замените уплотнительные кольца инжектора. Ключом S=13 затяните.'
  const spans = [span('part', 'уплотнительные кольца инжектора'), span('tool', 'S=13')]
  assert.deepEqual(marked(markPieces([text], spans)), [
    'Замените [part:уплотнительные кольца инжектора]. Ключом [tool:S=13] затяните.',
  ])
})

test('spans are found in order across paragraphs and list items, as drawn', () => {
  const texts = ['Снимите крышку.', 'Понадобится: динамометрический ключ', 'Замените прокладку крышки']
  const spans = [span('tool', 'динамометрический ключ'), span('part', 'прокладку крышки')]
  assert.deepEqual(marked(markPieces(texts, spans)), [
    'Снимите крышку.',
    'Понадобится: [tool:динамометрический ключ]',
    'Замените [part:прокладку крышки]',
  ])
})

test('the same words twice: each span takes the next one, not the first again', () => {
  const texts = ['Шайба и шайба']
  const spans = [span('part', 'шайба'), span('part', 'шайба')]
  // «Шайба» with a capital is not the span's text: the two lower-case ones are marked
  assert.deepEqual(marked(markPieces(texts, spans)), ['Шайба и [part:шайба]'])
  assert.deepEqual(marked(markPieces(['шайба и шайба'], spans)), ['[part:шайба] и [part:шайба]'])
})

test('a span that is not in the drawn text (a withdrawn claim) is passed over; the next is still found', () => {
  const texts = ['Затяните ключом S=17.']
  const spans = [span('part', 'болт крышки'), span('tool', 'S=17')]
  assert.deepEqual(marked(markPieces(texts, spans)), ['Затяните ключом [tool:S=17].'])
})

test('a later span that also happens to stand earlier does not skip the spans before it', () => {
  // «ключ» stands unmarked in the first line; the first span, «щуп», is in the second
  const texts = ['Возьмите ключ.', 'Проверьте щупом: щуп 0,25. Ключ — ключ S=13']
  const spans = [span('tool', 'щуп'), span('tool', 'ключ S=13')]
  assert.deepEqual(marked(markPieces(texts, spans)), [
    'Возьмите ключ.',
    'Проверьте [tool:щуп]ом: щуп 0,25. Ключ — [tool:ключ S=13]',
  ])
})

test('no spans, an unknown kind, an empty piece: plain text', () => {
  assert.deepEqual(marked(markPieces(['Текст'], undefined)), ['Текст'])
  assert.deepEqual(marked(markPieces(['Текст'], [])), ['Текст'])
  assert.deepEqual(marked(markPieces([''], [])), [''])
  assert.deepEqual(usableSpans([span('fluid', 'масло'), span('part', '  ')]), [])
  assert.deepEqual(marked(markPieces(['Залейте масло'], [span('fluid', 'масло')])), ['Залейте масло'])
})

test('the hint shows the designation and page as sent; blanks are no designation', () => {
  assert.deepEqual(spanHint(span('part', 'x', { designation: '536.1003206-10', page: 152 })), {
    designation: '536.1003206-10',
    page: 152,
  })
  assert.deepEqual(spanHint(span('tool', 'x', { designation: ' ' })), { designation: null, page: null })
})
