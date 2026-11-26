import type { SourceItem } from '../api'
import { chipMark, claimText, withdrawnLine, type Inline } from '../lib/answer'
import { SourceChip } from './SourceChip'

/** A claim the server withdrew: the sentence struck, why it was withdrawn and the page it cited, in one
 *  block behind a warning bar, so the struck number is never read as a confirmed one. The chip stays active
 *  and carries no check mark, whatever else that page confirmed. Without the claim (an answer checked
 *  before the event listed its claims) the server's note is shown as it is. */
export function Withdrawn({
  part,
  sources,
  onOpen,
}: {
  part: Extract<Inline, { kind: 'withdrawn' }>
  sources: Record<string, SourceItem>
  onOpen: (s: SourceItem) => void
}) {
  const cited = part.handles.flatMap((handle) => sources[handle] ?? [])
  const chips = cited.map((source) => (
    <SourceChip key={source.handle} source={source} {...chipMark(source.handle, null)} onOpen={onOpen} />
  ))
  if (!part.claim)
    return (
      <>
        <span className="text-warn">{part.text}</span>
        {chips}
      </>
    )
  const line = withdrawnLine(part.claim, cited)
  return (
    <span className="my-[4px] block border-l-2 border-warn pl-[10px] wrap-anywhere">
      <del className="text-dim line-through">{claimText(part.claim.text)}</del>
      <span className="block text-[13px] text-warn">
        {line}
        {chips}
      </span>
    </span>
  )
}
