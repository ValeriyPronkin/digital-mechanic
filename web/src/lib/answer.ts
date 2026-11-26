// The imports name their files: the unit tests load this module in Node as it is (web/tests).
import type { ClaimMarks, Verification, WithdrawnClaim } from '../api.ts'
import { copy } from '../copy.ts'
import { nbspUnits, pageLabel } from './format.ts'

export type Inline =
  | { kind: 'text'; text: string }
  // The server's note in place of a claim it could not confirm, the pages that claim cited, and, once
  // the claim is matched to the event, the claim itself.
  // `groups`: how many groups of marks follow the note, by the server's rule (see GROUPS); `group`: which
  // group of its line the first of them is. The chips of the line are numbered by the same counter.
  | { kind: 'withdrawn'; text: string; handles: string[]; group: number; groups: number; claim?: WithdrawnClaim }
  // `repeat`: same manual as the chip before it. `group`: which group of marks of its line the chip
  // belongs to, by the server's rule. `own`: the line found for the sentence this chip follows, once
  // the event's `claims` are matched to the text (`attachClaims`).
  | { kind: 'source'; handle: string; group: number; repeat?: boolean; own?: OwnQuote }
/** What a chip opens its page with: the line of its own sentence, or none when that sentence confirmed
 *  no number on the page. */
export type OwnQuote = { quote: string | null; scanned: boolean }
export type Node =
  | { kind: 'section'; title: string }
  | { kind: 'paragraph'; inline: Inline[] }
  | { kind: 'ordered'; items: Inline[][] }
  | { kind: 'bullets'; items: Inline[][] }

const SECTIONS = new Set(copy.sections.map((s) => s.toLowerCase()))
// One or more handle groups in a row are one run: «[S8][S6]», «[S8], [S6]», «[S8; S6]». A handle is
// read in either case, as the server reads it (app/verify.py): «[s1]» is S1.
const GROUP = String.raw`\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]`
const HANDLES = new RegExp(`${GROUP}(?:\\s*[,;]?\\s*${GROUP})*`, 'gi')
// A group of marks as the server counts them for `verification.claims` (`verify._MARK_GROUP`): marks
// with nothing but whitespace between them. The run above, which is what is drawn together, also
// joins over one comma or semicolon: «[S1], [S4]» is one run and two groups. The server's rule is
// the one definition; a run is split by it only to find each chip's item.
const GROUPS = new RegExp(`${GROUP}(?:\\s*${GROUP})*`, 'gi')
const LIST_MARK = /^\s*(?:\d+[.)]|[-–—•])\s+/

/** «Момент 421–461 Н·м [S3].» → «Момент 421–461 Н·м.» and a source chip after it: the full stop or
 *  comma that follows a handle moves in front of the chip, so no punctuation is left hanging. The
 *  handles that follow a withdrawal note are the pages the withdrawn claim cited: they stay with it. */
export function inline(text: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  let group = 0 // groups of marks met so far on this line
  for (const m of text.matchAll(HANDLES)) {
    let end = m.index + m[0].length
    const punctuation = text.slice(end).match(/^[.,;:!?]+/)?.[0] ?? ''
    end += punctuation.length
    const before = text.slice(last, m.index).replace(/\s+$/, '') + punctuation
    const note = pushText(out, before)
    for (const marks of m[0].match(GROUPS) ?? []) {
      const handles = (marks.match(/S\d+/gi) ?? []).map((handle) => handle.toUpperCase())
      if (note) note.handles.push(...handles)
      else for (const handle of handles) out.push({ kind: 'source', handle, group })
      if (note && note.groups === 0) note.group = group
      if (note) note.groups += 1
      group += 1
    }
    last = end
  }
  pushText(out, text.slice(last))
  return out
}

const WITHDRAWN = new RegExp(`(${copy.thread.withdrawn}[^.]*\\.(?: ${copy.thread.withdrawnTail}\\.?)?)`)

/** Adds the text; returns the withdrawal note when the text ends with one. */
function pushText(out: Inline[], text: string) {
  let note: Extract<Inline, { kind: 'withdrawn' }> | undefined
  for (const part of text.split(WITHDRAWN)) {
    if (!part) continue
    if (part.startsWith(copy.thread.withdrawn)) {
      note = { kind: 'withdrawn', text: part, handles: [], group: 0, groups: 0 }
      out.push(note)
    } else {
      note = undefined
      out.push({ kind: 'text', text: nbspUnits(part) })
    }
  }
  return note
}

/** The agent writes plain text: section titles on their own line, numbered and dashed lists. */
export function parseAnswer(raw: string): Node[] {
  const nodes: Node[] = []
  const lines = raw.replace(/\*\*/g, '').split('\n')
  for (const lineRaw of lines) {
    const line = lineRaw.trim()
    if (!line) continue
    const bare = line.replace(/^#+\s*/, '').replace(/[:.]$/, '')
    if (SECTIONS.has(bare.toLowerCase())) {
      nodes.push({ kind: 'section', title: bare })
      continue
    }
    const ordered = line.match(/^\d+[.)]\s+(.*)$/)
    const bullet = line.match(/^[-–—•]\s+(.*)$/)
    const last = nodes[nodes.length - 1]
    if (ordered) {
      if (last?.kind === 'ordered') last.items.push(inline(ordered[1]))
      else nodes.push({ kind: 'ordered', items: [inline(ordered[1])] })
    } else if (bullet) {
      if (last?.kind === 'bullets') last.items.push(inline(bullet[1]))
      else nodes.push({ kind: 'bullets', items: [inline(bullet[1])] })
    } else {
      nodes.push({ kind: 'paragraph', inline: inline(line) })
    }
  }
  return nodes
}

const lines = (node: Node): Inline[][] =>
  node.kind === 'section' ? [] : node.kind === 'paragraph' ? [node.inline] : node.items

/** The withdrawn claim as the mechanic reads it struck: no handles, no list marker (the list keeps its own). */
export const claimText = (raw: string) =>
  nbspUnits(
    raw
      .replace(/\*\*/g, '')
      .replace(LIST_MARK, '')
      .replace(HANDLES, '')
      .replace(/\s+([.,;:!?])/g, '$1')
      .replace(/\s{2,}/g, ' ')
      .trim(),
  )

/** Gives every withdrawal note the claim it replaced. The server writes the notes into the text and lists
 *  the claims in the event in the same order, one item per note (app/verify.py). When the two do not line
 *  up one to one, nothing is attached: a note without its sentence is better than a note over the wrong
 *  sentence. The pages the claim cited come from the item's `handles`; an answer checked before the event
 *  carried them keeps the marks read off the text after the note. */
export function attachWithdrawn(nodes: Node[], withdrawn: WithdrawnClaim[] | undefined): Node[] {
  const notes = nodes.flatMap((node) => lines(node).flat()).filter((part) => part.kind === 'withdrawn')
  if (!withdrawn || withdrawn.length !== notes.length) return nodes
  notes.forEach((note, i) => {
    note.claim = withdrawn[i]
    if (Array.isArray(withdrawn[i].handles)) note.handles = [...withdrawn[i].handles]
  })
  return nodes
}

/** Marks every chip that cites the same manual as the chip before it, so that it shows the page only.
 *  A run starts again at a section title and after a withdrawn claim, whose own chips always name the
 *  manual. A handle the server never issued (`manualOf` gives nothing) shows no chip and is passed over. */
export function markRepeats(nodes: Node[], manualOf: (handle: string) => string | undefined): Node[] {
  let previous: string | undefined
  for (const node of nodes) {
    if (node.kind === 'section') previous = undefined
    for (const part of lines(node).flat()) {
      if (part.kind === 'withdrawn') previous = undefined
      if (part.kind !== 'source') continue
      const manual = manualOf(part.handle)
      if (manual === undefined) continue
      part.repeat = manual === previous
      previous = manual
    }
  }
  return nodes
}

export type WithdrawnWhy = keyof typeof copy.thread.withdrawnWhy
const WHY_BY_STATE: Record<string, WithdrawnWhy> = { unverified: 'not_on_page', uncited: 'no_source' }

/** Why a claim was withdrawn, as a key of `copy.thread.withdrawnWhy`: the verifier's `reason`; for an
 *  answer checked before the event had one, read off `state`. A value this build has no words for gets
 *  the neutral ones. */
export function withdrawnWhy(claim: Pick<WithdrawnClaim, 'state' | 'reason'>): WithdrawnWhy {
  if (claim.reason == null) return WHY_BY_STATE[claim.state] ?? 'other'
  return Object.hasOwn(copy.thread.withdrawnWhy, claim.reason) ? (claim.reason as WithdrawnWhy) : 'other'
}

/** The line under a struck claim: why it was withdrawn and what to do. It names the pages the claim
 *  cited when they are pages of one manual; pages of two manuals are not listed in one breath, as if
 *  they were one document: the chips under the line name each. */
export function withdrawnLine(
  claim: Pick<WithdrawnClaim, 'state' | 'reason'>,
  cited: { manual_id: string; pdf_page: number }[],
): string {
  const why = copy.thread.withdrawnWhy
  const reason = withdrawnWhy(claim)
  if (reason !== 'not_on_page') return why[reason]()
  if (cited.length === 0) return why.other()
  if (new Set(cited.map((source) => source.manual_id)).size > 1) return copy.thread.withdrawnOnCited
  const pages = pageLabel(cited.map((source) => source.pdf_page).join(', '))
  return cited.length === 1 ? why.not_on_page(pages) : copy.thread.withdrawnOnPages(pages)
}

/** The marks of a chip. The check mark belongs to the page, not to the sentence: the server found a
 *  number of the answer on it. The chip of a withdrawn claim (`marks` is null) carries none, whatever
 *  else that page confirmed. */
export function chipMark(handle: string, marks: { verified: Set<string>; scanned: Set<string> } | null) {
  return { verified: marks?.verified.has(handle) ?? false, scanned: marks?.scanned.has(handle) ?? false }
}

/** Gives every chip the line found for its own sentence. The event lists one item per group of marks in
 *  the checked text, in text order; the groups are counted here by the same rule, line by line. When
 *  the two counts differ, or the event has no items (an answer checked before it carried them, or one
 *  the server could not line up itself), nothing is attached and every chip keeps the page's one line
 *  from `quotes`: an older answer opens as it always did, never on a line picked by a wrong count. */
export function attachClaims(nodes: Node[], claims: ClaimMarks[] | undefined): Node[] {
  if (!claims?.length) return nodes
  const rows = nodes.flatMap(lines)
  // One counter numbers the groups of a line, a note's and the chips' alike: the line has as many as the
  // highest index met, plus one. (Adding the notes' groups to the chips' would count a note twice when a
  // marked sentence follows it on the line.)
  const groupsIn = (row: Inline[]) =>
    row.reduce((n, part) => {
      if (part.kind === 'source') return Math.max(n, part.group + 1)
      if (part.kind === 'withdrawn' && part.groups > 0) return Math.max(n, part.group + part.groups)
      return n
    }, 0)
  if (rows.reduce((n, row) => n + groupsIn(row), 0) !== claims.length) return nodes
  let before = 0 // groups on the lines above
  for (const row of rows) {
    // On its line a chip's `group` counts the groups of a withdrawal note too: `inline` numbers them all.
    for (const part of row) {
      if (part.kind !== 'source') continue
      const found = claims[before + part.group].handles.find((entry) => entry.handle === part.handle)
      // A handle the item does not list cannot have a line of its own: no line rather than a guess.
      part.own = found ? { quote: found.quote, scanned: found.scanned } : { quote: null, scanned: false }
    }
    before += groupsIn(row)
  }
  return nodes
}

/** The line of the page shown as «Найдено на странице» when a chip is opened, and marked on the page.
 *  The chip's own line when the event gave one for its sentence (`own`), and none when it says that
 *  sentence confirmed no number on the page. Without `own` (an older answer), the page's one line.
 *  None for the chip of a withdrawn claim: a line the server has for that page belongs to another claim. */
export function quoteOf(verification: Verification | undefined, handle: string, withdrawn: boolean, own?: OwnQuote) {
  if (withdrawn) return undefined
  return own ? (own.quote ?? undefined) : verification?.quotes[handle]
}

/** Whether that line was read from the page image («по скану»), as the verifier said. Goes with the
 *  line: nothing where there is no line. */
export function quoteFromScan(
  verification: Verification | undefined,
  handle: string,
  withdrawn: boolean,
  own?: OwnQuote,
) {
  if (withdrawn) return undefined
  return own ? (own.quote === null ? undefined : own.scanned) : verification?.scanned?.includes(handle)
}

/** Under an answer: how many claims the server looked up on the pages they cite and how many of them it
 *  withdrew, and whether any chip carries the check mark the legend explains. Null when the server had
 *  nothing to look up. A claim is counted by the server; one without a number but with a page mark it
 *  must not have (a hypothesis) is a claim too, so the line does not say «с числами». */
export function checkSummary(verification: Verification | undefined) {
  if (!verification) return null
  const { verified, unverified, uncited } = verification.counts
  const withdrawn = unverified + uncited
  if (verified + withdrawn === 0) return null
  return { line: copy.thread.checked(verified + withdrawn, withdrawn), legend: verification.verified.length > 0 }
}
