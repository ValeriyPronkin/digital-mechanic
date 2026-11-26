import type { Verification } from '../api'
import { copy } from '../copy'
import { checkSummary } from '../lib/answer'
import { CheckMark } from './SourceChip'

/** Under an answer: how many claims the server looked up on the cited pages and how many of them it
 *  withdrew, and what the check mark on a chip means. Nothing when there was nothing to look up. */
export function CheckSummary({ verification }: { verification: Verification | undefined }) {
  const summary = checkSummary(verification)
  if (!summary) return null
  return (
    <p className="flex flex-wrap items-center gap-x-[12px] gap-y-[2px] text-[13px] leading-[1.35] text-dim">
      <span>{summary.line}</span>
      {summary.legend && (
        <span className="inline-flex items-center gap-[4px]">
          <span className="text-accent">
            <CheckMark />
          </span>
          {copy.thread.verifiedLegend}
        </span>
      )}
    </p>
  )
}
