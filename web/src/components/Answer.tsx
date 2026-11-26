import type { SourceItem, Verification } from '../api'
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
  onOpen: (s: SourceItem, withdrawn: boolean, own?: OwnQuote) => void
}

function Line({ inline, sources, verified, scanned, onOpen }: LineProps) {
  return (
    <>
      {inline.map((part, i) =>
        part.kind === 'text' ? (
          <span key={i}>{part.text}</span>
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
export function Answer({
  text,
  verification,
  onOpen,
  ...marks
}: { text: string; verification?: Verification } & Props) {
  const withClaims = attachWithdrawn(parseAnswer(text), verification?.withdrawn)
  const withRuns = markRepeats(withClaims, (handle) => marks.sources[handle]?.manual_id)
  const nodes = attachClaims(withRuns, verification?.claims)
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
              <Line inline={node.inline} {...marks} onOpen={open} />
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
                <Line inline={item} {...marks} onOpen={open} />
              </li>
            ))}
          </List>
        )
      })}
      <CheckSummary verification={verification} />
    </div>
  )
}
