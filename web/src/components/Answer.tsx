import { useState, type ReactNode } from 'react'
import type { AnswerSpan, SourceItem, Verification } from '../api'
import { copy } from '../copy'
import {
  attachClaims,
  attachWithdrawn,
  chipMark,
  markRepeats,
  parseAnswer,
  quoteFromScan,
  quoteOf,
  type Inline,
  type Node,
  type OwnQuote,
} from '../lib/answer'
import { citedHandles, footnotes, splitLead, withoutSources, type CitedDoc } from '../lib/footnotes'
import { chipLabel } from '../lib/format'
import { markPieces, spanHint, usableSpans, type Piece } from '../lib/spans'
import { CheckSummary } from './CheckSummary'
import { CheckMark } from './SourceChip'
import { Withdrawn } from './Withdrawn'

type Sources = Record<string, SourceItem>
type Marks = { sources: Sources; verified: Set<string>; scanned: Set<string> }
type Props = Marks & {
  // `quote` is the line of the page the server found a number on, for «Найдено на странице»;
  // `scanned` says that line was read from the page image.
  onOpen: (s: SourceItem, quote?: string, scanned?: boolean) => void
}
type Open = (s: SourceItem, withdrawn: boolean, own?: OwnQuote) => void
// Inside the answer a mark says whether it is the mark of a withdrawn claim and, when the server found
// one, hands over the line of its own sentence.
type LineProps = Marks & {
  inline: Inline[]
  numberOf: Map<string, number>
  pieces: Map<Inline, Piece[]> // the text parts with parts and tools marked (§8)
  onOpen: Open
}

/** How a part or a tool stands out: `underline` — its colour, underlined (parts solid, tools dashed);
 *  `pill` — its colour on a tinted background, like the page chips, with a small icon before the word.
 *  One constant, so the choice (issue #173) is one line. */
export const SPAN_LOOK: 'underline' | 'pill' = 'pill'

const SPAN_TONE = {
  underline: {
    part: 'text-part underline decoration-1 underline-offset-[3px] decoration-part/70',
    tool: 'text-tool underline decoration-1 underline-offset-[3px] decoration-tool/70 decoration-dashed',
  },
  pill: {
    part: 'text-part bg-part/15 rounded-md px-1 box-decoration-clone',
    tool: 'text-tool bg-tool/15 rounded-md px-1 box-decoration-clone',
  },
}[SPAN_LOOK]

/** A wrench for a tool, a hex nut for a part: 0.85em, so it follows the size of the text. */
function SpanIcon({ type }: { type: AnswerSpan['type'] }) {
  if (SPAN_LOOK !== 'pill') return null
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="mr-[0.2em] inline-block size-[0.85em] align-[-0.08em]"
      aria-hidden
    >
      {type === 'tool' ? (
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
      ) : (
        <>
          <path d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z" />
          <circle cx="12" cy="12" r="3.5" />
        </>
      )}
    </svg>
  )
}

/** A part or a tool in the answer: its own colour, underlined. A tap opens its hint right under the line of
 *  text: what it is, the designation and the page as the server sent them, and the page itself when the
 *  answer cites it. Inline rather than a floating tip, so it never covers the text and works by touch. */
function Marked({ span, sources, onOpen }: { span: AnswerSpan; sources: Sources; onOpen: (s: SourceItem) => void }) {
  const [open, setOpen] = useState(false)
  const { designation, page } = spanHint(span)
  const source = span.ref ? sources[span.ref] : undefined
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`relative inline before:absolute before:-inset-y-2 before:inset-x-0 before:content-[''] ${SPAN_TONE[span.type]}`}
      >
        <SpanIcon type={span.type} />
        {span.text}
      </button>
      {open && (
        <span
          role="note"
          className="mx-0.5 inline-flex flex-wrap items-baseline gap-x-2 rounded-md border border-line bg-surface-2 px-2 py-0.5 align-baseline text-[13px] leading-snug"
        >
          <span className={span.type === 'part' ? 'text-part' : 'text-tool'}>{copy.spans.kind[span.type]}</span>
          {designation && (
            <span>
              <span className="text-dim">{copy.spans.designation}</span> {designation}
            </span>
          )}
          {page !== null && <span>{copy.spans.page(page)}</span>}
          {!designation && page === null && <span className="text-dim">{copy.spans.noDetails}</span>}
          {source && (
            <button
              type="button"
              onClick={() => onOpen(source)}
              className="relative text-accent before:absolute before:-inset-y-3 before:inset-x-0 before:content-['']"
            >
              {copy.spans.open}
            </button>
          )}
        </span>
      )}
    </>
  )
}

/** A small numbered mark after a claim, in place of the chip: the number of the page in the list under the
 *  answer, ✓ when the server found the claim's numbers on it. A tap opens the page, on the line of this
 *  sentence, as the chip did. The tap area reaches 40 px high and 12 px past each side, so a small mark is
 *  still easy to hit; the screen reader reads the manual and the page. `data-chip`: the sheet finds the
 *  marks of the thread by it. */
function Footnote({
  n,
  source,
  verified,
  scanned,
  onOpen,
}: {
  n: number
  source: SourceItem
  verified: boolean
  scanned: boolean
  onOpen: (s: SourceItem) => void
}) {
  const label = chipLabel(source)
  return (
    <button
      type="button"
      data-chip
      onClick={() => onOpen(source)}
      aria-label={copy.answer.footnote(n, `${label.manual}, ${label.page}`)}
      title={scanned ? copy.thread.scannedHint : verified ? copy.thread.verifiedLegend : undefined}
      className="group/fn relative mx-[2px] inline-flex align-[0.12em] text-[12px] leading-none text-accent before:absolute before:-inset-x-[12px] before:-inset-y-[12px] before:content-['']"
    >
      <span className="relative inline-flex min-h-[18px] min-w-[18px] items-center justify-center gap-[2px] rounded-[5px] border border-line bg-surface-2 px-[4px] group-hover/fn:border-accent">
        {verified && <CheckMark label={copy.thread.verifiedLegend} />}
        {n}
        {scanned && <span className="text-warn">·</span>}
      </span>
    </button>
  )
}

function Line({ inline, numberOf, pieces, sources, verified, scanned, onOpen }: LineProps) {
  return (
    <>
      {inline.map((part, i) => {
        if (part.kind === 'text')
          return (
            <span key={i}>
              {(pieces.get(part) ?? [{ text: part.text }]).map((p, k) =>
                p.span ? <Marked key={k} span={p.span} sources={sources} onOpen={(s) => onOpen(s, false)} /> : p.text,
              )}
            </span>
          )
        if (part.kind === 'withdrawn')
          return <Withdrawn key={i} part={part} sources={sources} onOpen={(s) => onOpen(s, true)} />
        const source = sources[part.handle]
        const n = numberOf.get(part.handle)
        if (!source || n === undefined) return null // a handle the server never issued is not a source
        // two handles of one page in a row are one mark
        const prev = inline[i - 1]
        if (prev?.kind === 'source' && numberOf.get(prev.handle) === n) return null
        return (
          <Footnote
            key={i}
            n={n}
            source={source}
            {...chipMark(part.handle, { verified, scanned })}
            onOpen={(s) => onOpen(s, false, part.own)}
          />
        )
      })}
    </>
  )
}

function Blocks({
  nodes,
  ...line
}: Marks & { nodes: Node[]; numberOf: Map<string, number>; pieces: Map<Inline, Piece[]>; onOpen: Open }) {
  return nodes.map((node, i) => {
    if (node.kind === 'section')
      return (
        <h3 key={i} className="pt-2 text-[13px] font-semibold tracking-wide text-dim uppercase first:pt-0">
          {node.title}
        </h3>
      )
    if (node.kind === 'paragraph')
      return (
        <p key={i}>
          <Line inline={node.inline} {...line} />
        </p>
      )
    const List = node.kind === 'ordered' ? 'ol' : 'ul'
    return (
      <List
        key={i}
        className={`space-y-1.5 pl-5 ${node.kind === 'ordered' ? 'list-decimal' : 'list-disc'} marker:text-dim`}
      >
        {node.items.map((item, j) => (
          <li key={j}>
            <Line inline={item} {...line} />
          </li>
        ))}
      </List>
    )
  })
}

/** «Страницы руководства»: each page the answer cites, once, by document — «РЭ ЯМЗ-236М2 — стр. 31 ✓, 34».
 *  The number is the one of its marks in the text. Each page is a button that opens it. */
function Pages({ docs, verified, scanned, onOpen }: Marks & { docs: CitedDoc[]; onOpen: Open }) {
  if (docs.length === 0) return null
  return (
    <section className="space-y-2 border-t border-line pt-3" aria-label={copy.answer.pages}>
      <h3 className="text-[13px] font-semibold tracking-wide text-dim uppercase">{copy.answer.pages}</h3>
      {docs.map((doc) => (
        <div key={doc.manual_id} className="space-y-1.5">
          <p className="text-[13px] text-dim">{chipLabel(doc.pages[0].source).manual}</p>
          <div className="flex flex-wrap gap-2">
            {doc.pages.map((page) => {
              const ok = page.handles.some((h) => verified.has(h))
              const read = !ok && page.handles.some((h) => scanned.has(h))
              return (
                <button
                  key={page.n}
                  type="button"
                  data-chip
                  onClick={() => onOpen(page.source, false)}
                  title={read ? copy.thread.scannedHint : ok ? copy.thread.verifiedLegend : undefined}
                  className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2.5 text-[14px] text-accent hover:border-accent"
                >
                  <span className="text-[12px] text-dim">{page.n}</span>
                  {ok && <CheckMark label={copy.thread.verifiedLegend} />}
                  <span className="whitespace-nowrap">{chipLabel(page.source).page}</span>
                  {read && <span className="whitespace-nowrap text-warn">· {copy.thread.scanned}</span>}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </section>
  )
}

/** The two colours, once under an answer that has them: the jury and a new mechanic learn them here. */
function Legend({ spans }: { spans: AnswerSpan[] }) {
  const kinds = (['part', 'tool'] as const).filter((k) => spans.some((s) => s.type === k))
  return (
    <p className="flex flex-wrap gap-x-3 text-[13px] text-dim">
      <span>{copy.spans.legendTitle}:</span>
      {kinds.map((k) => (
        <span key={k} className={SPAN_TONE[k]}>
          <SpanIcon type={k} />
          {copy.spans.legend[k]}
        </span>
      ))}
    </p>
  )
}

/** Every text part of the answer, in the order it is drawn: «Коротко», then the rest. */
function textParts(nodes: readonly Node[]): Extract<Inline, { kind: 'text' }>[] {
  const lines = nodes.flatMap((n) => (n.kind === 'paragraph' ? [n.inline] : n.kind === 'section' ? [] : n.items))
  return lines.flat().filter((p): p is Extract<Inline, { kind: 'text' }> => p.kind === 'text')
}

/** From 900 px the thread is wide and the answer is read whole: «Весь ответ» starts open there. */
const wide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 900px)').matches

/** The agent's text, compact: «Коротко» — the first paragraph, larger; the rest under «Весь ответ»; small
 *  numbered marks after claims instead of chips; one list of the manual's pages under the answer, without
 *  repeats. The server's text is drawn as it came: nothing is rewritten, only laid out.
 *  `verification` is the server's check of that text: the claims it withdrew and the counts under the answer.
 *  Model-written text wraps anywhere when it has to: one long token must not push the thread sideways.
 *  «Весь ответ» is a button, not a `<details>`: the scenes of the video (scripts/e2e.py) count `<details>`
 *  to see that an answer is finished. */
export function Answer({
  text,
  verification,
  spans,
  afterLead,
  onOpen,
  ...marks
}: {
  text: string
  verification?: Verification
  spans?: AnswerSpan[] // parts and tools in the answer, each in its colour (§8)
  // Always in sight, never folded under «Весь ответ»: right under «Коротко» (the manuals disagree, D-20 —
  // Валерий, 27.11: folded, it was not seen). Without a lead, at the top of the answer.
  afterLead?: ReactNode
} & Props) {
  const [more, setMore] = useState(wide)
  const withClaims = attachWithdrawn(parseAnswer(text), verification?.withdrawn)
  const withRuns = markRepeats(withClaims, (handle) => marks.sources[handle]?.manual_id)
  const all = attachClaims(withRuns, verification?.claims)
  const { numberOf, docs } = footnotes(citedHandles(all), marks.sources)
  const drawn = withoutSources(all)
  const { lead, rest } = splitLead(drawn)
  const parts = textParts(drawn)
  const marked = markPieces(
    parts.map((p) => p.text),
    spans,
  )
  const pieces = new Map<Inline, Piece[]>(parts.map((p, i) => [p, marked[i]]))
  const shown = usableSpans(spans).filter((s) => marked.some((l) => l.some((p) => p.span === s)))
  // A mark opens the page on the line of its own sentence, not on the first line found on that page.
  const open: Open = (s, withdrawn, own) =>
    onOpen(s, quoteOf(verification, s.handle, withdrawn, own), quoteFromScan(verification, s.handle, withdrawn, own))
  const line = { ...marks, numberOf, pieces, onOpen: open }
  return (
    <div className="space-y-2 leading-[1.45] wrap-anywhere">
      {lead ? (
        <>
          <div className="text-[18px] leading-[1.4] font-medium">
            <Blocks nodes={[lead]} {...line} />
          </div>
          {afterLead}
          {more && <Blocks nodes={rest} {...line} />}
          <button
            type="button"
            aria-expanded={more}
            onClick={() => setMore(!more)}
            className="-my-1 flex min-h-11 items-center gap-1 text-accent"
          >
            {more ? copy.answer.less : copy.answer.more}
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={more ? 'rotate-180' : ''}
              aria-hidden
            >
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>
        </>
      ) : (
        <>
          {afterLead}
          <Blocks nodes={rest} {...line} />
        </>
      )}
      {shown.length > 0 && <Legend spans={shown} />}
      <Pages docs={docs} {...marks} onOpen={open} />
      <CheckSummary verification={verification} />
    </div>
  )
}
