import { useState } from 'react'
import type { SourceItem, Verification } from '../api'
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
type LineProps = Marks & { inline: Inline[]; numberOf: Map<string, number>; onOpen: Open }

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

function Line({ inline, numberOf, sources, verified, scanned, onOpen }: LineProps) {
  return (
    <>
      {inline.map((part, i) => {
        if (part.kind === 'text') return <span key={i}>{part.text}</span>
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

function Blocks({ nodes, ...line }: Marks & { nodes: Node[]; numberOf: Map<string, number>; onOpen: Open }) {
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

/** From 900 px the thread is wide and the answer is read whole: «Подробнее» starts open there. */
const wide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 900px)').matches

/** The agent's text, compact: «Коротко» — the first paragraph, larger; the rest under «Подробнее»; small
 *  numbered marks after claims instead of chips; one list of the manual's pages under the answer, without
 *  repeats. The server's text is drawn as it came: nothing is rewritten, only laid out.
 *  `verification` is the server's check of that text: the claims it withdrew and the counts under the answer.
 *  Model-written text wraps anywhere when it has to: one long token must not push the thread sideways.
 *  «Подробнее» is a button, not a `<details>`: the scenes of the video (scripts/e2e.py) count `<details>`
 *  to see that an answer is finished. */
export function Answer({
  text,
  verification,
  onOpen,
  ...marks
}: { text: string; verification?: Verification } & Props) {
  const [more, setMore] = useState(wide)
  const withClaims = attachWithdrawn(parseAnswer(text), verification?.withdrawn)
  const withRuns = markRepeats(withClaims, (handle) => marks.sources[handle]?.manual_id)
  const all = attachClaims(withRuns, verification?.claims)
  const { numberOf, docs } = footnotes(citedHandles(all), marks.sources)
  const { lead, rest } = splitLead(withoutSources(all))
  // A mark opens the page on the line of its own sentence, not on the first line found on that page.
  const open: Open = (s, withdrawn, own) =>
    onOpen(s, quoteOf(verification, s.handle, withdrawn, own), quoteFromScan(verification, s.handle, withdrawn, own))
  const line = { ...marks, numberOf, onOpen: open }
  return (
    <div className="space-y-2 leading-[1.45] wrap-anywhere">
      {lead ? (
        <>
          <div className="text-[18px] leading-[1.4] font-medium">
            <Blocks nodes={[lead]} {...line} />
          </div>
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
        <Blocks nodes={rest} {...line} />
      )}
      <Pages docs={docs} {...marks} onOpen={open} />
      <CheckSummary verification={verification} />
    </div>
  )
}
