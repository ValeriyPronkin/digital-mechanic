import { useState } from 'react'
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
  type OwnQuote,
} from '../lib/answer'
import { markPieces, spanHint, usableSpans, type Piece } from '../lib/spans'
import { CheckSummary } from './CheckSummary'
import { SourceChip } from './SourceChip'
import { Withdrawn } from './Withdrawn'

type Sources = Record<string, SourceItem>
type Marks = { sources: Sources; verified: Set<string>; scanned: Set<string> }
type Props = Marks & {
  // `quote` is the line of the page the server found a number on, for «Найдено на странице»;
  // `scanned` says that line was read from the page image.
  onOpen: (s: SourceItem, quote?: string, scanned?: boolean) => void
}
// Inside the answer a chip says whether it is the chip of a withdrawn claim and, when the server found
// one, hands over the line of its own sentence.
type LineProps = Marks & {
  inline: Inline[]
  pieces: Map<Inline, Piece[]> // the text parts with parts and tools marked
  onOpen: (s: SourceItem, withdrawn: boolean, own?: OwnQuote) => void
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

function Line({ inline, pieces, sources, verified, scanned, onOpen }: LineProps) {
  return (
    <>
      {inline.map((part, i) =>
        part.kind === 'text' ? (
          <span key={i}>
            {(pieces.get(part) ?? [{ text: part.text }]).map((p, k) =>
              p.span ? <Marked key={k} span={p.span} sources={sources} onOpen={(s) => onOpen(s, false)} /> : p.text,
            )}
          </span>
        ) : part.kind === 'withdrawn' ? (
          <Withdrawn key={i} part={part} sources={sources} onOpen={(s) => onOpen(s, true)} />
        ) : (
          <SourceChip
            key={i}
            source={sources[part.handle]}
            {...chipMark(part.handle, { verified, scanned })}
            repeat={part.repeat}
            onOpen={(s) => onOpen(s, false, part.own)}
          />
        ),
      )}
    </>
  )
}

/** The agent's text: section titles, short paragraphs, steps, and a source chip after each claim.
 *  `verification` is the server's check of that text: the claims it withdrew and the counts under the answer.
 *  Model-written text wraps anywhere when it has to: one long token must not push the thread sideways. */
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

/** Every text part of the answer, in the order it is drawn. */
function textParts(nodes: ReturnType<typeof attachClaims>): Extract<Inline, { kind: 'text' }>[] {
  const lines = nodes.flatMap((n) => (n.kind === 'paragraph' ? [n.inline] : n.kind === 'section' ? [] : n.items))
  return lines.flat().filter((p): p is Extract<Inline, { kind: 'text' }> => p.kind === 'text')
}

export function Answer({
  text,
  verification,
  spans,
  onOpen,
  ...marks
}: { text: string; verification?: Verification; spans?: AnswerSpan[] } & Props) {
  const withClaims = attachWithdrawn(parseAnswer(text), verification?.withdrawn)
  const withRuns = markRepeats(withClaims, (handle) => marks.sources[handle]?.manual_id)
  const nodes = attachClaims(withRuns, verification?.claims)
  const parts = textParts(nodes)
  const marked = markPieces(
    parts.map((p) => p.text),
    spans,
  )
  const pieces = new Map<Inline, Piece[]>(parts.map((p, i) => [p, marked[i]]))
  const shown = usableSpans(spans).filter((s) => marked.some((line) => line.some((p) => p.span === s)))
  // A chip opens the page on the line of its own sentence, not on the first line found on that page.
  const open = (s: SourceItem, withdrawn: boolean, own?: OwnQuote) =>
    onOpen(s, quoteOf(verification, s.handle, withdrawn, own), quoteFromScan(verification, s.handle, withdrawn, own))
  return (
    <div className="space-y-2 leading-[1.45] wrap-anywhere">
      {nodes.map((node, i) => {
        if (node.kind === 'section')
          return (
            <h3 key={i} className="pt-2 text-[13px] font-semibold tracking-wide text-dim uppercase first:pt-0">
              {node.title}
            </h3>
          )
        if (node.kind === 'paragraph')
          return (
            <p key={i}>
              <Line inline={node.inline} pieces={pieces} {...marks} onOpen={open} />
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
                <Line inline={item} pieces={pieces} {...marks} onOpen={open} />
              </li>
            ))}
          </List>
        )
      })}
      {shown.length > 0 && <Legend spans={shown} />}
      <CheckSummary verification={verification} />
    </div>
  )
}
