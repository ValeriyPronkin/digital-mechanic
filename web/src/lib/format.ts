import { copy } from '../copy.ts' // named in full: web/tests load this module in Node

const NBSP = '\u00a0'
const MONTHS = 'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split(' ')
const MONTHS_SHORT = 'янв фев мар апр мая июн июл авг сен окт ноя дек'.split(' ')

/** Date and time parts as written in the timestamp. A check made at 13:20 at the depot reads 13:20
 *  on every phone, whatever its time zone. Timestamps without an offset in them (ours, in UTC) are
 *  shown in local time. */
function parts(iso: string) {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::[\d.]+)?([+-]\d{2}:\d{2})$/)
  if (m) return { day: Number(m[3]), month: Number(m[2]) - 1, time: `${m[4]}:${m[5]}` }
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return { day: d.getDate(), month: d.getMonth(), time: `${pad(d.getHours())}:${pad(d.getMinutes())}` }
}

/** 12 ноября */
export const dateRu = (iso: string) => `${parts(iso).day}${NBSP}${MONTHS[parts(iso).month]}`
/** 12 ноя */
export const dateShortRu = (iso: string) => `${parts(iso).day}${NBSP}${MONTHS_SHORT[parts(iso).month]}`
/** 12 ноября, 14:20 */
export const dateTimeRu = (iso: string) => `${dateRu(iso)}, ${parts(iso).time}`

/** 0,76 */
export const num = (value: number, digits = 2) => value.toFixed(digits).replace('.', ',')

/** A plate typed in Cyrillic finds the Latin one in the fleet file, and the other way round. */
const LOOKALIKE: Record<string, string> = {
  А: 'A',
  В: 'B',
  Е: 'E',
  К: 'K',
  М: 'M',
  Н: 'H',
  О: 'O',
  Р: 'P',
  С: 'C',
  Т: 'T',
  У: 'Y',
  Х: 'X',
}
export const plateKey = (s: string) =>
  s
    .toUpperCase()
    .replace(/[\s-]/g, '')
    .replace(/[АВЕКМНОРСТУХ]/g, (c) => LOOKALIKE[c])

/** стр. 41 */
export const pageLabel = (page: number | string) => `${copy.page.abbr}${NBSP}${page}`

/** 236.01.01 РК, стр. 41 */
export const sourceLabel = (s: { short: string; pdf_page: number }) => `${s.short}, ${pageLabel(s.pdf_page)}`

/** What a source chip says. The page is always there; a chip that cites the same manual as the chip
 *  before it leaves the manual out: «236.01.01 РК, стр. 41», then «стр. 54». The manual goes by its
 *  chip name, which fits a phone; a source stored before that name existed has only `short`. */
export const chipLabel = (s: { short: string; chip?: string; pdf_page: number }, repeat = false) => ({
  manual: repeat ? null : s.chip || s.short,
  page: pageLabel(s.pdf_page),
})

// Units a number is written with in the manuals (docs/voice.md, [units], and what the answers add).
const UNITS = [
  '°\\s?[CС]?',
  '%',
  'мкм',
  'мм',
  'см',
  'км',
  'м',
  'Н\\s?[·⋅∙*]\\s?м',
  'кгс\\s?[·⋅∙*]\\s?м',
  'кгс/см[²2]',
  'кгс',
  'МПа',
  'кПа',
  'Па',
  'бар',
  'атм',
  'об/мин',
  'мин[⁻-][¹1]',
  'мин',
  'ч',
  'с',
  'мл',
  'л',
  'кг',
  'г',
  'кВт',
  'Вт',
  'В',
  'А',
  'Ом',
]
const BEFORE_UNIT = new RegExp(`(\\d)[ \\t]+(?=(?:${UNITS.join('|')})(?![\\p{L}\\d]))`, 'gu')
const AFTER_ABBR = /(стр\.|№)[ \t]+(?=\d)/g
const UNIT_SLASH = /(об|кгс)\/(?=мин|см)/g
const RANGE = /(\d[–…±])(?=\d)/g
const WORD_JOINER = '\u2060'

/** A number stays on one line with its unit, «стр.» and «№» with their number (docs/voice.md):
 *  «75–100 °C», «421–461 Н·м», «стр. 41». The value itself is not broken either: not after the slash
 *  of a unit («об/мин»), not inside a range («0,25–0,30», «75,5…80,4»). Only the space changes, and an
 *  invisible joiner goes after the slash and the dash; a space that is already non-breaking is left
 *  alone. A word that only looks like a unit («5 с половиной») gets the same space, which costs nothing. */
export const nbspUnits = (text: string) =>
  text
    .replace(BEFORE_UNIT, `$1${NBSP}`)
    .replace(AFTER_ABBR, `$1${NBSP}`)
    .replace(UNIT_SLASH, `$1/${WORD_JOINER}`)
    .replace(RANGE, `$1${WORD_JOINER}`)

/** Russian plural: `plural(3, ['обращение', 'обращения', 'обращений'])` → «обращения». */
export const plural = (n: number, forms: readonly [string, string, string]) => {
  const tens = Math.abs(n) % 100
  const ones = tens % 10
  if (tens > 10 && tens < 20) return forms[2]
  return ones === 1 ? forms[0] : ones >= 2 && ones <= 4 ? forms[1] : forms[2]
}
