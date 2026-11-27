// The page of each work and part of a ticket: the chip on the ticket sheet, the lines of a sent ticket and
// what a ticket stored before the lines shows. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { SourceItem, TicketLine } from '../src/api.ts'
import { itemSource, lineSource, pagesByManual, sheetLines, verdictWord, worksWithPages } from '../src/lib/sheet.ts'

const NBSP = ' '
const RK = 'ЯМЗ-236, ЯМЗ-238. Руководство по ремонту'
const RE = 'ЯМЗ-236М2, ЯМЗ-238М2. Руководство по эксплуатации 236-3902150-Б РЭ'
const page = (manual: string, n: number) => `${manual}, стр.${NBSP}${n}`
const line = (text: string, manual: string, pdf_page: number, manual_id: string | null = null): TicketLine => ({
  text,
  source: '',
  quote: '',
  scanned: false,
  manual,
  manual_id,
  short: manual === RK ? 'РК ЯМЗ-236' : 'РЭ ЯМЗ-236',
  pdf_page,
})

const TICKET = {
  operations: ['Проверить и подрегулировать тепловые зазоры', 'Заменить манометр'],
  spare_parts: ['Прокладка крышки (236-1007118), стр. 169'],
  references: [
    { manual: RK, pdf_page: 269 },
    { manual: RE, pdf_page: 53 },
  ],
}
const LINES = {
  operations: [line(TICKET.operations[0], RK, 269, 'yamz-236-rk'), line(TICKET.operations[1], RE, 53, 'yamz-236-re')],
  spare_parts: [line(TICKET.spare_parts[0], RE, 169, 'yamz-236-re')],
}

test('a sent ticket that keeps its lines shows every work and part with its own page, openable', () => {
  const sheet = sheetLines(TICKET, LINES)
  assert.deepEqual(
    sheet.works.map((w) => w.page),
    [page('РК ЯМЗ-236', 269), page('РЭ ЯМЗ-236', 53)], // the manual by its short name, as on a chip
  )
  assert.deepEqual(sheet.pages, []) // the pages are not listed again
  assert.deepEqual(sheet.works[0].source, {
    handle: '',
    manual_id: 'yamz-236-rk',
    short: 'РК ЯМЗ-236',
    chip: 'РК ЯМЗ-236',
    designation: RK,
    pdf_page: 269,
  })
  assert.equal(sheet.parts[0].source?.pdf_page, 169)
})

test('a line without the manual id is words only; a line without a page lists the pages once', () => {
  const noId = { operations: LINES.operations.map((l) => ({ ...l, manual_id: null })), spare_parts: [] }
  const sheet = sheetLines({ ...TICKET, spare_parts: [] }, noId)
  assert.equal(
    sheet.works.every((w) => w.page && !('source' in w)),
    true,
  )
  const unknown = {
    ...LINES,
    spare_parts: [{ ...LINES.spare_parts[0], manual: null, manual_id: null, short: null, pdf_page: null }],
  }
  const partial = sheetLines(TICKET, unknown)
  assert.equal(partial.parts[0].page, null) // a part the manual's list does not have: no page invented
  assert.deepEqual(partial.pages, []) // the works have theirs
  const workUnknown = {
    ...LINES,
    operations: [{ ...LINES.operations[0], manual: null, pdf_page: null }, LINES.operations[1]],
  }
  assert.deepEqual(sheetLines(TICKET, workUnknown).pages, pagesByManual(TICKET.references))
})

test('a ticket stored without lines, or with lines that are not what was sent, shows the pages once', () => {
  const old = sheetLines(TICKET, null)
  assert.deepEqual(old.pages, [page(RK, 269), page(RE, 53)])
  assert.equal(
    old.works.some((w) => w.page || w.source),
    false,
  )
  const reworded = {
    ...LINES,
    operations: [{ ...LINES.operations[0], text: 'Подрегулировать зазоры' }, LINES.operations[1]],
  }
  assert.deepEqual(sheetLines(TICKET, reworded), old)
  const swapped = { ...LINES, operations: [LINES.operations[1], LINES.operations[0]] }
  assert.deepEqual(sheetLines(TICKET, swapped), old)
  // one page: every work is on it
  assert.deepEqual(worksWithPages(['А', 'Б'], [{ manual: RE, pdf_page: 53 }]), [
    { text: 'А', page: page(RE, 53), scanned: false },
    { text: 'Б', page: page(RE, 53), scanned: false },
  ])
})

test('the chip on the ticket sheet: the cited source when the answer has it, else the page on the line', () => {
  const cited: SourceItem = {
    handle: 'S1',
    manual_id: 'yamz-236-rk',
    short: 'РК ЯМЗ-236',
    designation: RK,
    pdf_page: 269,
  }
  const work = { ...LINES.operations[0], source: 'S1' }
  assert.equal(itemSource(work, { S1: cited }), cited)
  // a page of the matrix the answer did not cite: the line's own page
  assert.equal(itemSource({ ...work, source: 'S7' }, { S1: cited })?.pdf_page, 269)
  // a draft saved before pages: no chip
  assert.equal(itemSource({ text: 'Работа', source: '', quote: '', scanned: false }, {}), undefined)
  assert.equal(lineSource({ manual_id: 'yamz-236-rk', manual: RK, pdf_page: null }), null)
})

test('the verdict word of the conclusion is cut off to be printed in bold', () => {
  assert.deepEqual(
    verdictWord('Вероятно: клапанный механизм. Акустическая проверка S-0009 от 17 ноября 2026. Требуется дефектовка.'),
    ['Вероятно', 'клапанный механизм. Акустическая проверка S-0009 от 17 ноября 2026. Требуется дефектовка.'],
  )
  assert.deepEqual(verdictWord('Предварительно: коробка передач'), ['Предварительно', 'коробка передач'])
  // a conclusion the model wrote before the server did (#136) is printed as it is
  for (const text of ['По результату акустической проверки: клапанный механизм.', 'оценка: 0,92', '']) {
    assert.deepEqual(verdictWord(text), ['', text])
  }
})
