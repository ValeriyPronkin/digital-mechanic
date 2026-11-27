import { useState } from 'react'
import type { GuideBlock, SourceItem } from '../api'
import { copy } from '../copy'
import { SourceChip } from './SourceChip'

/** «Привод распределительного вала…» → «привод распределительного вала…»; «ЗМЗ-…» keeps its capitals. */

type Sources = Record<string, SourceItem>

function Pages({ guide, sources, onOpen }: { guide: GuideBlock; sources: Sources; onOpen: (s: SourceItem) => void }) {
  return (
    <ul className="space-y-1.5 text-[13px] text-dim">
      {guide.pages.map((page) => (
        <li key={page.source}>
          {page.why}
          <SourceChip source={sources[page.source]} onOpen={onOpen} />
        </li>
      ))}
    </ul>
  )
}

/** The text a mechanic takes to a defect inspection when no ticket can be sent. Built by the server. */
function Recommendation({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    // A part of the card under a rule, not a box in it: no card inside a card (docs/design.md).
    <div className="border-t border-line pt-3">
      <p className="text-[13px] font-semibold tracking-wide text-dim uppercase">{copy.guide.recommendation}</p>
      <p className="mt-1 text-[14px] select-all">{text}</p>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => setCopied(true))
        }}
        className="mt-1 min-h-12 text-[13px] text-accent hover:underline"
      >
        {copied ? copy.guide.copied : copy.guide.copyText}
      </button>
    </div>
  )
}

/** What the coverage registry says when the manual cannot back the fault: the engine has no such unit,
 *  or the manual has only a general check. For a covered fault nothing is shown, because the answer
 *  carries the pages; when there is no answer (`listPages`: the model was unavailable or refused), they are listed. */
export function GuideCard({
  guide,
  sources,
  onOpen,
  listPages = false,
}: {
  guide: GuideBlock
  sources: Sources
  onOpen: (s: SourceItem) => void
  listPages?: boolean
}) {
  if (guide.coverage === 'covered') {
    if (!listPages || guide.pages.length === 0) return null
    return (
      <section className="space-y-2 rounded-xl border border-line bg-surface p-4">
        <p className="text-[13px] font-semibold tracking-wide text-dim uppercase">{copy.guide.pages}</p>
        <Pages guide={guide} sources={sources} onOpen={onOpen} />
      </section>
    )
  }
  const notCovered = guide.coverage === 'not_covered'
  return (
    <section className="relative overflow-hidden rounded-xl border border-line bg-surface">
      <div className={`absolute inset-y-0 left-0 w-1 ${notCovered ? 'bg-mute' : 'bg-warn'}`} aria-hidden />
      <div className="space-y-2 py-4 pr-4 pl-5">
        <p className={`text-[13px] font-semibold tracking-wide uppercase ${notCovered ? 'text-dim' : 'text-warn'}`}>
          {copy.guide.word[guide.coverage]}
        </p>
        {notCovered ? (
          <>
            {/* The label above says «такого узла нет» and the verdict card says what to do: here are the
                fact with its page and the text to take away, each said once on the screen. */}
            {guide.proof && (
              <p>
                {guide.proof}.
                {guide.proof_source && <SourceChip source={sources[guide.proof_source]} onOpen={onOpen} />}
              </p>
            )}
            {guide.recommendation && <Recommendation text={guide.recommendation} />}
          </>
        ) : (
          <>
            <p className="text-[17px] leading-[1.35] font-semibold text-balance">{copy.guide.inspectionOnly}</p>
            <Pages guide={guide} sources={sources} onOpen={onOpen} />
          </>
        )}
      </div>
    </section>
  )
}
