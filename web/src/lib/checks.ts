// The imports name their files: the unit tests load this module in Node as it is (web/tests).
import type { SessionBrief, VerdictBlock } from '../api.ts'
import { copy } from '../copy.ts'
import { num } from './format.ts'

/** How one check is named in a list of checks (the picker under the chart, the chart's own labels): the
 *  colour of its dot and its word.
 *
 *  A check whose result does not fit the engine (`fits_engine === false`: it named a fault this engine
 *  cannot have) is an error of the acoustic model, not a diagnosis. It gets the word of its verdict card,
 *  «не диагноз», and a neutral dot: neither the red of «отклонение», which the card denies, nor the green
 *  of «норма», which nobody found. Without the field (an older server) the status speaks. */
export function checkLook(check: Pick<SessionBrief, 'status' | 'fits_engine'>): { dot: string; word: string } {
  if (check.fits_engine === false) return { dot: 'bg-mute', word: copy.verdict.word.mismatch }
  return { dot: DOT[check.status], word: copy.status[check.status] }
}

const DOT = { normal: 'bg-ok', anomaly: 'bg-stop', check_failed: 'bg-mute' } as const

/** The figures of a check whose result does not fit the engine, in one line and in the words the card
 *  already uses: «По данным проверки: оценка 0,76 из 1, уверенность 0,82, запись чистая». They are
 *  the acoustic model's output for a fault the engine cannot have, so they are attributed and small,
 *  never the card's large facts. */
export function checkData(v: Pick<VerdictBlock, 'anomaly_score' | 'confidence' | 'signal_quality'>): string {
  const lower = (word: string) => word.charAt(0).toLowerCase() + word.slice(1)
  const facts = [
    v.anomaly_score !== null && `${lower(copy.verdict.score)} ${num(v.anomaly_score)} ${copy.verdict.scoreOf}`,
    v.confidence !== null && `${lower(copy.verdict.confidence)} ${num(v.confidence)}`,
    `${lower(copy.verdict.recording)} ${copy.quality[v.signal_quality]}`,
  ]
  return `${copy.verdict.byCheck}: ${facts.filter(Boolean).join(', ')}`
}

/** The stretches of the chart's line: each joins checks that are readings of the engine, in order.
 *
 *  A failed recording (no score) breaks the line: nothing was measured between its neighbours. A check
 *  whose result does not fit the engine has a score that is not a reading: the line passes it by
 *  unbroken and joins the readings on either side, so the picture says what the trend sentence says,
 *  and the check's own point is left off the line at its height. `i` is the check's place on the axis. */
export function lineRuns<T extends Pick<SessionBrief, 'anomaly_score' | 'fits_engine'>>(
  sessions: T[],
): { s: T; i: number }[][] {
  const runs: { s: T; i: number }[][] = []
  sessions.forEach((s, i) => {
    if (s.anomaly_score === null) runs.push([])
    else if (s.fits_engine !== false) (runs[runs.length - 1] ?? runs[runs.push([]) - 1]).push({ s, i })
  })
  return runs
}

// Badges of a fleet row (app/urgency.py, app/fleet.py) that are drawn as labels beside what the row says.
// The others («повторить запись», «норма после отклонения») stand in place of a line of the row.
const LABELS = new Set(['ticket_created', 'result_mismatch'])

/** What a fleet row does with its badges.
 *
 *  `labels` are drawn as outlined labels next to the row's line: «заявка создана», and «результат не
 *  подходит двигателю». `instead` is the one badge that replaces a line. `withReason`: the vehicle's
 *  latest check named a fault its engine cannot have; the status word is still the one of the check
 *  before it («норма», say), so the row also shows the server's reason line, which says what happened
 *  and what to do, in the mechanic's list too, where a row otherwise has no reason line. */
export function rowBadges(badges: { code: string; label: string }[]): {
  labels: string[]
  instead: string | null
  withReason: boolean
} {
  return {
    labels: badges.filter((b) => LABELS.has(b.code)).map((b) => b.label),
    instead: badges.find((b) => !LABELS.has(b.code))?.label ?? null,
    withReason: badges.some((b) => b.code === 'result_mismatch'),
  }
}
