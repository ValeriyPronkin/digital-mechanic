// A chip opens the page on the line of its own sentence (#85): how the items of `verification.claims`
// are matched to the chips of the checked text. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { ClaimMarks, Verification } from '../src/api.ts'
import { attachClaims, parseAnswer, quoteFromScan, quoteOf, type Inline } from '../src/lib/answer.ts'

const item = (...handles: [string, string | null, boolean?][]): ClaimMarks => ({
  handles: handles.map(([handle, quote, scanned = false]) => ({ handle, quote, scanned })),
})
// The page's one line, as `quotes` has always carried it: the line of the first sentence that cited the page.
const QUOTES = { S1: 'первая строка стр. 41', S2: 'первая строка стр. 19', S4: 'первая строка стр. 44', S5: '80±2 °С' }
const checked = (claims: ClaimMarks[] | undefined): Verification => ({
  verified: ['S1', 'S2', 'S4', 'S5'],
  quotes: QUOTES,
  counts: { verified: 1, unverified: 0, uncited: 0 },
  scanned: ['S4'],
  claims,
})
/** What every chip of the answer opens its page with, in text order: [handle, the line, read from the image]. */
function opened(text: string, verification: Verification) {
  const nodes = attachClaims(parseAnswer(text), verification.claims)
  const parts: Inline[] = nodes.flatMap((n) =>
    n.kind === 'section' ? [] : n.kind === 'paragraph' ? n.inline : n.items.flat(),
  )
  return parts.flatMap((part) => {
    if (part.kind === 'source')
      return [
        [
          part.handle,
          quoteOf(verification, part.handle, false, part.own),
          quoteFromScan(verification, part.handle, false, part.own),
        ],
      ]
    if (part.kind === 'withdrawn')
      return part.handles.map((handle) => [
        handle,
        quoteOf(verification, handle, true),
        quoteFromScan(verification, handle, true),
      ])
    return []
  })
}
const NOTE = 'Утверждение снято: число не найдено на указанной странице. Сверьте со страницей.'

test('two sentences that cite one page open it on two different lines', () => {
  const text =
    'Основной клапан начинает открываться при 80±2 °С [S5]. Активное открытие заканчивается при 93±2 °С [S5].'
  const both = checked([item(['S5', '80±2 °С']), item(['S5', '93±2 °С', true])])
  assert.deepEqual(opened(text, both), [
    ['S5', '80±2 °С', false],
    ['S5', '93±2 °С', true], // its own line and its own «по скану», not the first sentence's
  ])
  // An answer checked before the event carried the items: both chips open on the page's one line, as before.
  assert.deepEqual(opened(text, checked(undefined)), [
    ['S5', '80±2 °С', false],
    ['S5', '80±2 °С', false],
  ])
})

test('a sentence without a number opens its page with no line, not with another sentence’s', () => {
  const text = 'Ход клапана должен быть 8 мм [S5].\nНеисправный термостат заменить новым [S5].'
  const verification = checked([item(['S5', '8 мм']), item(['S5', null])])
  assert.deepEqual(opened(text, verification), [
    ['S5', '8 мм', false],
    ['S5', undefined, undefined],
  ])
})

test('the marks of a withdrawal note are a group too; its chip opens with no line', () => {
  const text = `${NOTE} [S1] [S4]\nМомент затяжки 421–461 Н·м [S1].`
  const verification = checked([item(['S1', null], ['S4', null]), item(['S1', '421-461 Н*м'])])
  assert.deepEqual(opened(text, verification), [
    ['S1', undefined, undefined],
    ['S4', undefined, undefined],
    ['S1', '421-461 Н*м', false],
  ])
})

test('a withdrawal note before a marked sentence on one line: two groups, the chip takes the second item', () => {
  const text = `${NOTE} [S1] Термостат открывается при 80±2 °С [S5].`
  const verification = checked([item(['S1', null]), item(['S5', '80±2 °С', true])])
  assert.deepEqual(opened(text, verification), [
    ['S1', undefined, undefined], // the note's own chip
    ['S5', '80±2 °С', true], // its own line, not the fallback: the line's groups are counted once
  ])
  // The fallback would have read the page's one line and the page-level «по скану» instead.
  assert.deepEqual(opened(text, checked(undefined))[1], ['S5', QUOTES.S5, false])
})

test('a withdrawal note between two marked sentences: three groups in the order written', () => {
  const text = `Зазор 0,25 мм [S2]. ${NOTE} [S1] [S4] Ход клапана 8 мм [S5].\nМомент 421–461 Н·м [S1].`
  const verification = checked([
    item(['S2', '0,25 мм']),
    item(['S1', null], ['S4', null]),
    item(['S5', '8 мм']),
    item(['S1', '421-461 Н*м']),
  ])
  assert.deepEqual(opened(text, verification), [
    ['S2', '0,25 мм', false],
    ['S1', undefined, undefined],
    ['S4', undefined, undefined],
    ['S5', '8 мм', false],
    ['S1', '421-461 Н*м', false], // the next line starts after all three groups of the first
  ])
  // A note with no marks at all (no page was cited) takes no item.
  const bare = 'Утверждение снято: для числа не указана страница руководства. Ход клапана 8 мм [S5].'
  assert.deepEqual(opened(bare, checked([item(['S5', '8 мм'])])), [['S5', '8 мм', false]])
})

test('marks with only spaces between them are one group: «[S1] [S4]», «[S1][S4]», «[S1, S4]»', () => {
  for (const marks of ['[S1] [S4]', '[S1][S4]', '[S1, S4]', '[S1; S4]', '[ s1 ]  [s4]']) {
    const verification = checked([item(['S1', '421-461 Н*м'], ['S4', null])])
    assert.deepEqual(
      opened(`Момент затяжки 421–461 Н·м ${marks}.`, verification),
      [
        ['S1', '421-461 Н*м', false],
        ['S4', undefined, undefined], // only S1 holds the numbers
      ],
      marks,
    )
  }
})

test('a comma or a semicolon between marks parts two groups: the chips of one run take items i and i+1', () => {
  // Drawn together as one run (web/src/lib/answer.ts, HANDLES), counted as the server counts (GROUPS).
  const text = 'Зазор 0,25 мм [S2]. Момент 421–461 Н·м [S1], [S4]. Давление 400–700 кПа [S1];[S4].'
  const verification = checked([
    item(['S2', '0,25 мм']),
    item(['S1', '421-461 Н*м']),
    item(['S4', 'та же строка в приложении', true]),
    item(['S1', '400-700 кПа']),
    item(['S4', null]),
  ])
  assert.deepEqual(opened(text, verification), [
    ['S2', '0,25 мм', false],
    ['S1', '421-461 Н*м', false],
    ['S4', 'та же строка в приложении', true],
    ['S1', '400-700 кПа', false],
    ['S4', undefined, undefined],
  ])
  // One run on the screen: nothing is drawn between the two chips.
  const [paragraph] = parseAnswer('Момент 421–461 Н·м [S1], [S4].')
  assert.ok(paragraph.kind === 'paragraph')
  assert.deepEqual(
    paragraph.inline.map((p) => (p.kind === 'source' ? `${p.handle}:${p.group}` : p.kind)),
    ['text', 'S1:0', 'S4:1'],
  )
})

test('groups are counted through the whole answer: paragraphs, list items, a list’s opening line', () => {
  const text = [
    'Что проверить',
    'Моменты затяжки по руководству [S1]:',
    '- болты крышек 421–461 Н·м;',
    '- гайки головок 240–260 Н·м [S4]',
    '1. Проверить давление 400–700 кПа [S2]',
    '2. **Заменить** термостат [S5]',
  ].join('\n')
  const verification = checked([
    item(['S1', '421-461 Н*м']), // the opening line takes the line of the first item below it
    item(['S4', '240-260 Н*м', true]),
    item(['S2', '400-700 кПа']),
    item(['S5', null]),
  ])
  assert.deepEqual(opened(text, verification), [
    ['S1', '421-461 Н*м', false],
    ['S4', '240-260 Н*м', true],
    ['S2', '400-700 кПа', false],
    ['S5', undefined, undefined],
  ])
})

test('when the items do not line up with the groups, every chip falls back to the page’s one line', () => {
  const text = 'Зазор 0,25 мм [S2]. Момент 421–461 Н·м [S1], [S4].'
  const fallback = [
    ['S2', QUOTES.S2, false],
    ['S1', QUOTES.S1, false],
    ['S4', QUOTES.S4, true],
  ]
  // one item short, one too many, none, and a record that never had the field
  assert.deepEqual(opened(text, checked([item(['S2', 'x']), item(['S1', 'y'])])), fallback)
  assert.deepEqual(
    opened(text, checked([item(['S2', 'x']), item(['S1', 'y']), item(['S4', 'z']), item(['S4', 'w'])])),
    fallback,
  )
  assert.deepEqual(opened(text, checked([])), fallback)
  assert.deepEqual(opened(text, checked(undefined)), fallback)
})

test('marks on neighbouring lines: the server could not line them up and sent no items', () => {
  // «…[S1]» ends a line and «[S2]…» starts the next. The server's count over the whole text joins the two,
  // its count by sentence does not, so it sends `claims: []`: the page's one line is what there is.
  const text = 'Момент затяжки 421–461 Н·м [S1]\n[S2] Давление 400–700 кПа.'
  assert.deepEqual(opened(text, checked([])), [
    ['S1', QUOTES.S1, false],
    ['S2', QUOTES.S2, false],
  ])
  // Counted here they are two groups, line by line: had the server sent one joined item, it would not match.
  assert.deepEqual(opened(text, checked([item(['S1', 'a'], ['S2', 'b'])])), [
    ['S1', QUOTES.S1, false],
    ['S2', QUOTES.S2, false],
  ])
})

test('a mark that starts the next line: the server sends no items, both chips open on the page’s one line', () => {
  // Probed on the server: «…80±2 °С [S1]\n[S1] Конец…» comes back with `claims: []`.
  const text = 'Клапан начинает открываться при 80±2 °С [S1]\n[S1] Конец открытия при 93±2 °С.'
  assert.deepEqual(opened(text, checked([])), [
    ['S1', QUOTES.S1, false],
    ['S1', QUOTES.S1, false],
  ])
})

test('a heading line with a mark and no number: its chip opens the page with no line and no mark', () => {
  // Probed on the server: such a line gives an item with `quote: null`. It is not a list's opening line
  // that borrows the line of an item below: the sentences under it carry their own marks.
  const text = ['Что проверить [S5]', 'Клапан начинает открываться при 80±2 °С [S5].', 'Ход клапана 8 мм [S5].'].join(
    '\n',
  )
  const verification = checked([item(['S5', null]), item(['S5', '80±2 °С']), item(['S5', '8 мм'])])
  assert.deepEqual(opened(text, verification), [
    ['S5', undefined, undefined], // although `quotes` has a line for this page
    ['S5', '80±2 °С', false],
    ['S5', '8 мм', false],
  ])
})

test('a handle its item does not list opens with no line rather than a guessed one', () => {
  const verification = checked([item(['S2', '0,25 мм'])])
  assert.deepEqual(opened('Зазор 0,25 мм [S1].', verification), [['S1', undefined, undefined]])
})

test('the chip of a withdrawn claim never gets a line, whatever the event says', () => {
  const own = { quote: 'строка', scanned: true }
  assert.equal(quoteOf(checked(undefined), 'S1', true, own), undefined)
  assert.equal(quoteFromScan(checked(undefined), 'S1', true, own), undefined)
})
