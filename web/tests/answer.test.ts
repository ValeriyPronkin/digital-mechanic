// How the evidence in an answer reads (#73): the label of a source chip, the space before a unit, the
// withdrawn claim. Run with `npm test` (Node's own test runner, no dependency).
import assert from 'node:assert/strict'
import test from 'node:test'
import type { Verification } from '../src/api.ts'
import {
  attachWithdrawn,
  checkSummary,
  chipMark,
  claimText,
  markRepeats,
  parseAnswer,
  quoteFromScan,
  quoteOf,
  withdrawnLine,
  withdrawnWhy,
  type Inline,
  type Node,
} from '../src/lib/answer.ts'
import { chipLabel, nbspUnits, plural } from '../src/lib/format.ts'
import { copy } from '../src/copy.ts'

const NBSP = '\u00a0'
const JOIN = String.fromCharCode(0x2060) // word joiner: invisible, no line break after the slash of a unit
const visible = (text: string) => text.replaceAll(JOIN, '')
const RE = { manual_id: 'yamz-236-re', short: '236-3902150-Б РЭ' }
const RK = { manual_id: 'yamz-236-rk', short: '236.01.01 РК' }
const SOURCES: Record<string, { manual_id: string; short: string; pdf_page: number }> = {
  S1: { ...RE, pdf_page: 54 },
  S2: { ...RE, pdf_page: 19 },
  S3: { ...RK, pdf_page: 41 },
  S4: { ...RK, pdf_page: 44 },
}
const manualOf = (handle: string) => SOURCES[handle]?.manual_id
const parts = (nodes: Node[]): Inline[] =>
  nodes.flatMap((n) => (n.kind === 'section' ? [] : n.kind === 'paragraph' ? n.inline : n.items.flat()))
/** The chips of an answer as the mechanic reads them, in order. */
const chips = (answer: string) =>
  parts(markRepeats(parseAnswer(answer), manualOf)).flatMap((p) => {
    if (p.kind !== 'source' || !SOURCES[p.handle]) return []
    const { manual, page } = chipLabel(SOURCES[p.handle], p.repeat)
    return [manual ? `${manual}, ${page}` : page]
  })

test('a chip names its manual and its page; a repeated source shows the page only', () => {
  assert.deepEqual(chipLabel(SOURCES.S3), { manual: '236.01.01 РК', page: `стр.${NBSP}41` })
  assert.deepEqual(chipLabel(SOURCES.S3, true), { manual: null, page: `стр.${NBSP}41` })
})

test('the chip goes by the manual’s chip name, and by its short name when a stored thread has none', () => {
  const stored = { short: 'Руководство по ремонту ЗМЗ-5234.10', pdf_page: 137 }
  assert.equal(chipLabel({ ...stored, chip: 'ЗМЗ-5234.10' }).manual, 'ЗМЗ-5234.10')
  assert.equal(chipLabel(stored).manual, 'Руководство по ремонту ЗМЗ-5234.10')
  assert.equal(chipLabel({ ...stored, chip: '' }).manual, 'Руководство по ремонту ЗМЗ-5234.10')
  assert.equal(chipLabel({ ...stored, chip: 'ЗМЗ-5234.10' }, true).manual, null)
})

test('the first chip of a run shows the manual, the chips after it only the page', () => {
  const answer =
    'Причина одна [S1].\nДавление 400–700 кПа [S2].\n- Прокладка [S1]\n- Момент 421–461 Н·м [S3]\n- Шаг [S4]'
  assert.deepEqual(chips(answer), [
    `236-3902150-Б РЭ, стр.${NBSP}54`,
    `стр.${NBSP}19`,
    `стр.${NBSP}54`,
    `236.01.01 РК, стр.${NBSP}41`, // another manual: named again
    `стр.${NBSP}44`,
  ])
})

test('a run starts again at a section title, and a handle the server never issued is passed over', () => {
  const answer = 'Что слышно\nСтук [S1].\nЕщё [S9] и ещё [S2].\nЧто проверить\n1. Зазор [S2]\n2. Щуп [S1]'
  assert.deepEqual(chips(answer), [
    `236-3902150-Б РЭ, стр.${NBSP}54`,
    `стр.${NBSP}19`,
    `236-3902150-Б РЭ, стр.${NBSP}19`, // the first chip under «Что проверить»
    `стр.${NBSP}54`,
  ])
})

test('several handles after one claim are one run', () => {
  assert.deepEqual(chips('Момент затяжки [S3][S4], давление [S1; S2].'), [
    `236.01.01 РК, стр.${NBSP}41`,
    `стр.${NBSP}44`,
    `236-3902150-Б РЭ, стр.${NBSP}54`,
    `стр.${NBSP}19`,
  ])
})

test('a number keeps its unit on its line', () => {
  const cases: [string, string][] = [
    ['должна быть 75–100 °C.', `должна быть 75–100${NBSP}°C.`],
    ['до 105 °С', `до 105${NBSP}°С`], // Cyrillic С
    ['421–461 Н·м (43–47 кгс·м)', `421–461${NBSP}Н·м (43–47${NBSP}кгс·м)`],
    ['400–700 кПа (4–7 кгс/см²) при 2100 об/мин', `400–700${NBSP}кПа (4–7${NBSP}кгс/см²) при 2100${NBSP}об/мин`],
    ['зазор 0,70…0,85 мм;', `зазор 0,70…0,85${NBSP}мм;`],
    ['через 500 ч и 20 мин', `через 500${NBSP}ч и 20${NBSP}мин`],
    ['не более 10 %', `не более 10${NBSP}%`],
    ['12 В, 2 кВт, 55 А', `12${NBSP}В, 2${NBSP}кВт, 55${NBSP}А`],
    ['стр. 41 и № 5', `стр.${NBSP}41 и №${NBSP}5`],
  ]
  for (const [raw, shown] of cases) assert.equal(visible(nbspUnits(raw)), shown)
})

test('a value is not broken inside: not after the slash of a unit, not inside a range', () => {
  assert.equal(nbspUnits('2100 об/мин'), `2100${NBSP}об/${JOIN}мин`)
  assert.equal(nbspUnits('4–7 кгс/см²'), `4–${JOIN}7${NBSP}кгс/${JOIN}см²`)
  assert.equal(nbspUnits('0,25–0,30 мм'), `0,25–${JOIN}0,30${NBSP}мм`)
  assert.equal(nbspUnits('75,5…80,4 Н·м'), `75,5…${JOIN}80,4${NBSP}Н·м`)
  assert.equal(nbspUnits('80±2 °C'), `80±${JOIN}2${NBSP}°C`)
  // A dash between words and a designation with a hyphen are left as they are.
  for (const same of ['Решение – за главным механиком', '236-3902150-Б РЭ', '40904.1000400-21'])
    assert.equal(nbspUnits(same), same)
})

test('only the space before a unit changes', () => {
  for (const same of [
    'Затянуть в 2 приёма', // a count, not a quantity
    'через 5 минут', // a word that starts like a unit
    '3 месяца, 4 цилиндра, 6 болтов',
    `уже 0,25${NBSP}мм`,
    'Проверить зазор щупом',
    'зазор и/или натяг', // a slash outside a unit
  ])
    assert.equal(nbspUnits(same), same)
  assert.equal(visible(nbspUnits('75–100 °C')).replace(NBSP, ' '), '75–100 °C')
})

test('the answer text is shown with the units tied to their numbers', () => {
  const [paragraph] = parseAnswer('Температура 75–100 °C [S1].')
  assert.deepEqual(paragraph, {
    kind: 'paragraph',
    inline: [
      { kind: 'text', text: `Температура 75–${JOIN}100${NBSP}°C.` },
      { kind: 'source', handle: 'S1', group: 0 },
    ],
  })
})

const NOT_ON_PAGE = 'Утверждение снято: число не найдено на указанной странице. Сверьте со страницей.'
const NO_SOURCE = 'Утверждение снято: для числа не указана страница руководства.'

test('a withdrawn claim keeps its sentence and the page it cited', () => {
  const checked = `Давление 400–700 кПа [S2].\n${NOT_ON_PAGE} [S3]\n${NO_SOURCE}\n1. Снять крышки [S1]\n2. ${NOT_ON_PAGE} [S3] [S4]`
  const withdrawn = [
    { text: 'Момент затяжки 430–470 Н·м [S3].', state: 'unverified', missing: ['430', '470'] },
    { text: 'Зазор в замке кольца 0,45–0,65 мм.', state: 'uncited', missing: ['0,45', '0,65'] },
    { text: '2. Затянуть гайки моментом **240–260 Н·м** [S3][S4].', state: 'unverified', missing: ['240', '260'] },
  ]
  const notes = parts(attachWithdrawn(parseAnswer(checked), withdrawn)).filter((p) => p.kind === 'withdrawn')
  assert.deepEqual(
    notes.map((n) => [visible(claimText(n.claim!.text)), n.handles, withdrawnWhy(n.claim!)]),
    [
      [`Момент затяжки 430–470${NBSP}Н·м.`, ['S3'], 'not_on_page'],
      [`Зазор в замке кольца 0,45–0,65${NBSP}мм.`, [], 'no_source'],
      [`Затянуть гайки моментом 240–260${NBSP}Н·м.`, ['S3', 'S4'], 'not_on_page'],
    ],
  )
  // The cited pages belong to the withdrawn block: they are not loose chips, and the next chip names its manual.
  const all = parts(markRepeats(attachWithdrawn(parseAnswer(checked), withdrawn), manualOf))
  assert.deepEqual(
    all.filter((p) => p.kind === 'source'),
    [
      { kind: 'source', handle: 'S2', group: 0, repeat: false },
      { kind: 'source', handle: 'S1', group: 0, repeat: false },
    ],
  )
})

test('claims are attached only when they line up with the notes one to one', () => {
  const nodes = attachWithdrawn(parseAnswer(`${NOT_ON_PAGE} [S3]\n${NO_SOURCE}`), [
    { text: 'Момент 430 Н·м [S3].', state: 'unverified' },
  ])
  assert.ok(parts(nodes).every((p) => p.kind !== 'withdrawn' || p.claim === undefined))
  assert.ok(parts(attachWithdrawn(parseAnswer(NO_SOURCE), undefined)).every((p) => !('claim' in p)))
})

test('the reason of a withdrawal: the verifier’s own, and the state for an answer checked before it had one', () => {
  for (const reason of ['not_on_page', 'no_source', 'other_variant', 'page_number', 'hypothesis'] as const) {
    assert.equal(withdrawnWhy({ state: 'unverified', reason }), reason) // the reason wins over the state
    assert.equal(withdrawnWhy({ state: 'uncited', reason }), reason)
    assert.match(copy.thread.withdrawnWhy[reason]('стр. 41'), /^(не подтверждено|без источника)/)
  }
  assert.equal(withdrawnWhy({ state: 'unverified' }), 'not_on_page')
  assert.equal(withdrawnWhy({ state: 'uncited' }), 'no_source')
  assert.equal(withdrawnWhy({ state: 'uncited', reason: null }), 'no_source')
  // Values this build has no words for get the neutral line, never a guess.
  for (const reason of ['made_up', 'toString', '']) assert.equal(withdrawnWhy({ state: 'unverified', reason }), 'other')
  assert.equal(withdrawnWhy({ state: 'something_new' }), 'other')
})

test('the line under a struck claim names the cited pages and says what to do', () => {
  // every page of one manual; two manuals are the next test
  const on = (reason: string | undefined, state: string, pages: number[]) =>
    withdrawnLine(
      { state, reason },
      pages.map((pdf_page) => ({ manual_id: 'yamz-236-rk', pdf_page })),
    )
  assert.equal(on('not_on_page', 'unverified', [41]), `не подтверждено на стр.${NBSP}41 — сверьте со страницей`)
  assert.equal(
    on('not_on_page', 'unverified', [41, 44]),
    `не подтверждено на стр.${NBSP}41, 44 — сверьте со страницами`,
  )
  assert.equal(on('not_on_page', 'unverified', []), 'не подтверждено — сверьте с руководством')
  assert.equal(on('no_source', 'uncited', []), 'без источника: страница руководства не указана')
  assert.equal(
    on('other_variant', 'unverified', [41]),
    'не подтверждено: страница относится к другой модификации двигателя',
  )
  assert.equal(on('page_number', 'uncited', []), 'не подтверждено: номер страницы вписан в ответ, а не дан ссылкой')
  assert.equal(on('hypothesis', 'uncited', []), 'не подтверждено: в предположении не бывает чисел и ссылок на страницы')
  assert.equal(on('made_up', 'unverified', [41]), 'не подтверждено — сверьте с руководством')
  // An answer checked before the event had `reason`.
  assert.equal(on(undefined, 'unverified', [41]), `не подтверждено на стр.${NBSP}41 — сверьте со страницей`)
  assert.equal(on(undefined, 'uncited', []), 'без источника: страница руководства не указана')
})

test('the pages a withdrawn claim cited come from the event, and from the marks in the text without it', () => {
  const OTHER_VARIANT = 'Утверждение снято: страница относится к другой модификации двигателя.'
  const checked = `${OTHER_VARIANT} [S3] [S4]\n${NOT_ON_PAGE} [S1]`
  const withEvent = parts(
    attachWithdrawn(parseAnswer(checked), [
      { text: 'Зазор 0,25 мм [S3][S4].', state: 'unverified', reason: 'other_variant', handles: ['S3', 'S4'] },
      { text: 'Момент 430 Н·м [S1][S99].', state: 'unverified', reason: 'not_on_page', handles: ['S1'] },
    ]),
  )
  assert.deepEqual(
    withEvent.map((p) => p.kind === 'withdrawn' && [p.handles, withdrawnWhy(p.claim!)]),
    [
      [['S3', 'S4'], 'other_variant'],
      [['S1'], 'not_on_page'],
    ],
  )
  const stored = parts(
    attachWithdrawn(parseAnswer(checked), [
      { text: 'Зазор 0,25 мм [S3][S4].', state: 'unverified' },
      { text: 'Момент 430 Н·м [S1].', state: 'unverified' },
    ]),
  )
  assert.deepEqual(
    stored.map((p) => p.kind === 'withdrawn' && p.handles),
    [['S3', 'S4'], ['S1']],
  )
  assert.ok(withEvent.concat(stored).every((p) => p.kind === 'withdrawn')) // no loose chip is left behind
})

test('pages of two manuals are not listed in one line as if they were one document', () => {
  const claim = { state: 'unverified', reason: 'not_on_page' }
  const rk = { manual_id: 'yamz-236-rk', pdf_page: 41 }
  const re = { manual_id: 'yamz-236-re', pdf_page: 19 }
  assert.equal(withdrawnLine(claim, [rk, re]), 'не подтверждено на указанных страницах — сверьте со страницами')
  assert.doesNotMatch(withdrawnLine(claim, [rk, re]), /\d/)
  assert.equal(
    withdrawnLine(claim, [rk, { ...rk, pdf_page: 44 }]),
    `не подтверждено на стр.${NBSP}41, 44 — сверьте со страницами`,
  )
})

test('a handle is read in either case, as the server reads it', () => {
  assert.deepEqual(parts(parseAnswer('Момент затяжки [s1], зазор [S2; s3].')), [
    { kind: 'text', text: 'Момент затяжки,' },
    { kind: 'source', handle: 'S1', group: 0 },
    { kind: 'text', text: ' зазор.' },
    { kind: 'source', handle: 'S2', group: 1 },
    { kind: 'source', handle: 'S3', group: 1 },
  ])
  assert.equal(
    visible(claimText('2. Затянуть [s3] моментом 240–260 Н·м [S3], [s4].')),
    `Затянуть моментом 240–260${NBSP}Н·м.`,
  )
  const [note] = parts(parseAnswer(`${NOT_ON_PAGE} [s3]`))
  assert.ok(note.kind === 'withdrawn')
  assert.deepEqual(note.handles, ['S3'])
})

const verification = (counts: [number, number, number], verified: string[] = []): Verification => ({
  verified,
  quotes: { S1: '421-461 Н*м (43-47 кгс*м)' },
  counts: { verified: counts[0], unverified: counts[1], uncited: counts[2] },
})

test('the line under an answer counts what the server counts: claims looked up, and those withdrawn', () => {
  assert.deepEqual(checkSummary(verification([5, 0, 0], ['S1'])), {
    line: 'Сверено утверждений: 5 · снято: 0',
    legend: true,
  })
  assert.deepEqual(checkSummary(verification([2, 3, 1], ['S1'])), {
    line: 'Сверено утверждений: 6 · снято: 4',
    legend: true,
  })
  // A hypothesis line with a page mark and no number is a claim the server looked up and withdrew: the line
  // does not call it a claim «с числами».
  assert.deepEqual(checkSummary(verification([0, 1, 0])), { line: 'Сверено утверждений: 1 · снято: 1', legend: false })
  assert.doesNotMatch(copy.thread.checked(1, 1), /числ/)
  assert.equal(checkSummary(verification([0, 0, 0])), null) // nothing to look up: no line
  assert.equal(checkSummary(undefined), null) // while the answer streams
})

test('the legend of the check mark is true of the page, not of the sentence before the chip', () => {
  // The mark is per page: a chip with it may follow a sentence that has no number at all.
  assert.equal(copy.thread.verifiedLegend, 'на странице найдено число из ответа')
  assert.deepEqual(checkSummary(verification([1, 0, 0]))?.legend, false) // no chip carries the mark: no legend
})

test('a chip of a withdrawn claim carries no mark, whatever else its page confirmed', () => {
  const marks = { verified: new Set(['S1', 'S2']), scanned: new Set(['S2']) }
  assert.deepEqual(chipMark('S1', marks), { verified: true, scanned: false })
  assert.deepEqual(chipMark('S2', marks), { verified: true, scanned: true })
  assert.deepEqual(chipMark('S3', marks), { verified: false, scanned: false })
  for (const handle of ['S1', 'S2', 'S3']) assert.deepEqual(chipMark(handle, null), { verified: false, scanned: false })
})

test('a withdrawn claim’s page opens without a quote; a confirmed one with the line the number was found on', () => {
  const checked = verification([1, 1, 0], ['S1'])
  assert.equal(quoteOf(checked, 'S1', false), '421-461 Н*м (43-47 кгс*м)')
  assert.equal(quoteOf(checked, 'S1', true), undefined) // the quote of that page belongs to another claim
  assert.equal(quoteOf(checked, 'S2', false), undefined)
  assert.equal(quoteOf(undefined, 'S1', false), undefined)
  // …and the same for «the quote was read from the page image», which the viewer takes with the quote
  const scanned = { ...checked, scanned: ['S1'] }
  assert.equal(quoteFromScan(scanned, 'S1', false), true)
  assert.equal(quoteFromScan(scanned, 'S2', false), false)
  assert.equal(quoteFromScan(scanned, 'S1', true), undefined)
  assert.equal(quoteFromScan(checked, 'S1', false), undefined) // a thread stored before the list existed
  assert.equal(quoteFromScan(undefined, 'S1', false), undefined)
})

const HYPOTHESES = 'Предположения, не из руководства'
const answerWithHypotheses = (lines: string[]) =>
  [
    'Что это может быть',
    'По руководству причина — зазор в клапанах 0,25–0,30 мм [S1].',
    'Чем это грозит',
    'Руководство запрещает работу двигателя с этим стуком [S2].',
    HYPOTHESES,
    ...lines,
    'Что проверить',
    '1. Проверить зазор щупом [S2]',
    '2. Затянуть гайки моментом 44–56 Н·м [S3]',
  ].join('\n')

test('a hypothesis block: its own section, dashed lines, no chips, and the chips around it keep their runs', () => {
  const answer = answerWithHypotheses(['- Возможен износ втулок.', '- Стоит послушать на холодном двигателе.'])
  const nodes = markRepeats(attachWithdrawn(parseAnswer(answer), []), manualOf)
  assert.deepEqual(
    nodes.map((n) => (n.kind === 'section' ? n.title : n.kind)),
    [
      'Что это может быть',
      'paragraph',
      'Чем это грозит',
      'paragraph',
      HYPOTHESES,
      'bullets',
      'Что проверить',
      'ordered',
    ],
  )
  const block = nodes[5]
  assert.deepEqual(block, {
    kind: 'bullets',
    items: [
      [{ kind: 'text', text: 'Возможен износ втулок.' }],
      [{ kind: 'text', text: 'Стоит послушать на холодном двигателе.' }],
    ],
  })
  // «Чем это грозит» and «Что проверить» are section titles like the others: each names the manual again.
  assert.deepEqual(chips(answer), [
    `236-3902150-Б РЭ, стр.${NBSP}54`,
    `236-3902150-Б РЭ, стр.${NBSP}19`,
    `236-3902150-Б РЭ, стр.${NBSP}19`,
    `236.01.01 РК, стр.${NBSP}41`,
  ])
})

test('a withdrawn hypothesis line: struck in its place in the block, with the reason and no chip', () => {
  const NOTE = 'Утверждение снято: в предположении не бывает чисел и ссылок на страницы.'
  const answer = answerWithHypotheses(['- Возможен износ втулок.', `- ${NOTE}`])
  const withdrawn = [
    { text: '- Зазор мог вырасти до 0,45 мм [S1].', state: 'unverified', reason: 'hypothesis', handles: [] },
  ]
  const nodes = markRepeats(attachWithdrawn(parseAnswer(answer), withdrawn), manualOf)
  const block = nodes[5]
  assert.ok(block.kind === 'bullets' && block.items.length === 2)
  const [note] = block.items[1]
  assert.ok(block.items[1].length === 1 && note.kind === 'withdrawn' && note.claim)
  assert.deepEqual(note.handles, [])
  assert.equal(visible(claimText(note.claim.text)), `Зазор мог вырасти до 0,45${NBSP}мм.`)
  assert.equal(withdrawnLine(note.claim, []), 'не подтверждено: в предположении не бывает чисел и ссылок на страницы')
  // The withdrawn line breaks no run that matters: the next section names its manual anyway.
  assert.deepEqual(chips(answer).slice(-2), [`236-3902150-Б РЭ, стр.${NBSP}19`, `236.01.01 РК, стр.${NBSP}41`])
})

test('lines with no sources and no numbers outside any section are plain text', () => {
  const answer = ['Возможен износ втулок.', '- Стоит послушать на холодном двигателе.', 'Зазор 0,25 мм [S3]'].join('\n')
  const nodes = markRepeats(attachWithdrawn(parseAnswer(answer), []), manualOf)
  assert.deepEqual(
    nodes.map((n) => n.kind),
    ['paragraph', 'bullets', 'paragraph'],
  )
  assert.deepEqual(chips(answer), [`236.01.01 РК, стр.${NBSP}41`])
})

test('«шаг» is declined by number in the action log', () => {
  const steps = (n: number) => `${n} ${plural(n, copy.thread.logSteps)}`
  assert.deepEqual([1, 2, 3, 4, 5, 6, 11, 12, 21, 22, 25].map(steps), [
    '1 шаг',
    '2 шага',
    '3 шага',
    '4 шага',
    '5 шагов',
    '6 шагов',
    '11 шагов',
    '12 шагов',
    '21 шаг',
    '22 шага',
    '25 шагов',
  ])
})
