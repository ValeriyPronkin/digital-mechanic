// A check whose result does not fit the engine (#94): how it is named in the check picker and in the chart,
// the one line of its figures on the verdict card, and its badge in a fleet row. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { copy } from '../src/copy.ts'
import { checkData, checkLook, lineRuns, rowBadges } from '../src/lib/checks.ts'

const places = (runs: { i: number }[][]) => runs.map((run) => run.map((p) => p.i))

test('the chart’s line joins the readings and passes by a check that does not fit the engine, unbroken', () => {
  // C808CM178: 0,19 0,09 0,07, then the unfit 0,76, then 0,18
  const scores = [0.19, 0.09, 0.07, 0.76, 0.18].map((anomaly_score, i) => ({ anomaly_score, fits_engine: i !== 3 }))
  assert.deepEqual(places(lineRuns(scores)), [[0, 1, 2, 4]])
  // the unfit check is the latest, or the first: the line ends, or starts, at a reading
  assert.deepEqual(places(lineRuns(scores.slice(0, 4))), [[0, 1, 2]])
  assert.deepEqual(places(lineRuns(scores.slice(3))), [[1]])
})

test('a failed recording still breaks the line, and a server without the flag draws every score', () => {
  const failed = [{ anomaly_score: 0.1 }, { anomaly_score: null }, { anomaly_score: 0.3 }, { anomaly_score: 0.4 }]
  assert.deepEqual(places(lineRuns(failed)), [[0], [2, 3]])
  assert.deepEqual(places(lineRuns([{ anomaly_score: 0.1 }, { anomaly_score: 0.76 }])), [[0, 1]])
})

test('the figures of a check that does not fit the engine are one attributed line in the card’s own words', () => {
  assert.equal(
    checkData({ anomaly_score: 0.76, confidence: 0.82, signal_quality: 'good' }),
    'По данным проверки: оценка 0,76 из 1, уверенность 0,82, запись чистая',
  )
  assert.equal(
    checkData({ anomaly_score: 0.9, confidence: 0.58, signal_quality: 'warning' }),
    'По данным проверки: оценка 0,90 из 1, уверенность 0,58, запись с помехами',
  )
  // a figure the check did not give is left out, not printed as «null»
  assert.equal(
    checkData({ anomaly_score: null, confidence: null, signal_quality: 'bad' }),
    'По данным проверки: запись непригодна',
  )
})

const TICKET = { code: 'ticket_created', label: 'заявка создана' }
const MISMATCH = { code: 'result_mismatch', label: 'результат не подходит двигателю' }
const REPEAT = { code: 'repeat_recording', label: 'повторить запись' }
const AFTER = { code: 'normal_after_anomaly', label: 'норма после отклонения' }

test('a fleet row: «результат не подходит двигателю» is a label beside the reason line, not instead of it', () => {
  assert.deepEqual(rowBadges([MISMATCH]), { labels: [MISMATCH.label], instead: null, withReason: true })
  assert.deepEqual(rowBadges([MISMATCH, TICKET]), {
    labels: [MISMATCH.label, TICKET.label],
    instead: null,
    withReason: true,
  })
})

test('the other badges of a fleet row are what they were', () => {
  assert.deepEqual(rowBadges([]), { labels: [], instead: null, withReason: false })
  assert.deepEqual(rowBadges([TICKET]), { labels: [TICKET.label], instead: null, withReason: false })
  assert.deepEqual(rowBadges([REPEAT]), { labels: [], instead: REPEAT.label, withReason: false })
  assert.deepEqual(rowBadges([AFTER, TICKET]), { labels: [TICKET.label], instead: AFTER.label, withReason: false })
})

test('a check is named by its status: a green, a red or a grey dot and the status word', () => {
  assert.deepEqual(checkLook({ status: 'normal' }), { dot: 'bg-ok', word: 'норма' })
  assert.deepEqual(checkLook({ status: 'anomaly' }), { dot: 'bg-stop', word: 'отклонение' })
  assert.deepEqual(checkLook({ status: 'check_failed' }), { dot: 'bg-mute', word: 'запись непригодна' })
})

test('a check whose result does not fit the engine is no «отклонение»: a neutral dot and the card’s word', () => {
  const look = checkLook({ status: 'anomaly', fits_engine: false })
  assert.deepEqual(look, { dot: 'bg-mute', word: 'не диагноз' })
  assert.equal(look.word, copy.verdict.word.mismatch) // one wording, the verdict card's
  assert.notEqual(look.dot, 'bg-stop') // not the red of an anomaly
  assert.notEqual(look.dot, 'bg-ok') // and not the green of a normal check
  assert.notEqual(look.word, copy.status.anomaly)
})

test('the flag decides only when it says «does not fit»', () => {
  assert.deepEqual(checkLook({ status: 'anomaly', fits_engine: true }), { dot: 'bg-stop', word: 'отклонение' })
  assert.deepEqual(checkLook({ status: 'anomaly', fits_engine: undefined }), { dot: 'bg-stop', word: 'отклонение' })
  assert.deepEqual(checkLook({ status: 'normal', fits_engine: true }), { dot: 'bg-ok', word: 'норма' })
  assert.deepEqual(checkLook({ status: 'check_failed', fits_engine: true }), {
    dot: 'bg-mute',
    word: 'запись непригодна',
  })
})
