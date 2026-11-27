import { useState } from 'react'
import type { VerdictBlock } from '../api'
import { copy } from '../copy'
import { checkData } from '../lib/checks'
import { dateTimeRu, num } from '../lib/format'

const tone = (v: VerdictBlock): { bar: string; text: string } => {
  // a result that is no diagnosis (a failed recording, a fault the engine cannot have) is not an alarm
  if (v.case === 'failed' || v.case === 'mismatch') return { bar: 'bg-mute', text: 'text-dim' }
  if (v.case === 'normal') return { bar: 'bg-ok', text: 'text-ok' }
  if (v.case === 'anomaly' && v.urgency?.level === 'high') return { bar: 'bg-stop', text: 'text-stop' }
  return { bar: 'bg-warn', text: 'text-warn' }
}

const urgencyTone = { high: 'text-stop', medium: 'text-warn', low: 'text-text' } as const

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[13px] text-dim">{label}</dt>
      <dd className="mt-0.5 text-[17px] font-semibold">
        {value}
        {note && (
          <span className="block text-[13px] font-normal text-dim min-[480px]:ml-1 min-[480px]:inline">{note}</span>
        )}
      </dd>
    </div>
  )
}

/** The result of a check, readable in ten seconds. Rendered from the tool result, before any model text. */
export function VerdictCard({ verdict: v }: { verdict: VerdictBlock }) {
  const [showForeign, setShowForeign] = useState(false)
  const t = tone(v)
  const mismatch = v.case === 'mismatch'
  return (
    <section className="relative overflow-hidden rounded-xl border border-line bg-surface">
      <div className={`absolute inset-y-0 left-0 w-1 ${t.bar}`} aria-hidden />
      <div className="space-y-3 py-4 pr-4 pl-5">
        <div>
          <p className={`text-[13px] font-semibold tracking-wide uppercase ${t.text}`}>{copy.verdict.word[v.case]}</p>
          <h2 className="mt-1 text-[22px] leading-[1.15] font-semibold text-balance">{v.headline}</h2>
          {/* A result that does not fit the engine: its first line is what to do, and reads as that. */}
          {v.lines.map((line, i) => (
            <p key={line} className={`mt-1.5 ${mismatch && i === 0 ? 'font-semibold' : 'text-dim'}`}>
              {line}
            </p>
          ))}
          {/* …and the check's figures are the model's own output for a type the engine cannot have:
              one small line, not the card's facts. */}
          {mismatch && <p className="mt-1.5 text-[13px] text-dim">{checkData(v)}</p>}
        </div>

        {/* Columns as wide as what they hold: in three equal ones «Уверенность» (81 px) ran into
            «Запись» on a 320 px screen, where a column is 75 px. */}
        {!mismatch && v.anomaly_score !== null && v.confidence !== null && (
          <dl className="grid grid-cols-[auto_auto_auto] justify-between gap-x-2.5 border-t border-line pt-3">
            <Fact label={copy.verdict.score} value={num(v.anomaly_score)} note={copy.verdict.scoreOf} />
            <Fact label={copy.verdict.confidence} value={v.confidence_word ?? ''} note={num(v.confidence)} />
            <Fact label={copy.verdict.recording} value={copy.quality[v.signal_quality]} />
          </dl>
        )}

        {v.urgency && (
          <details className="group border-t border-line pt-3">
            <summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center justify-between gap-x-3 [&::-webkit-details-marker]:hidden">
              <span>
                <span className="text-dim">{copy.verdict.urgency}: </span>
                <span className={`font-semibold ${urgencyTone[v.urgency.level]}`}>{v.urgency.word}</span>
              </span>
              <span className="text-[13px] text-accent group-open:hidden">{copy.verdict.why}</span>
              <span className="hidden text-[13px] text-accent group-open:inline">{copy.verdict.hide}</span>
              {v.urgency.action && <span className="basis-full pb-2">{v.urgency.action}</span>}
            </summary>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-dim marker:text-mute">
              {v.urgency.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </details>
        )}

        {v.description && v.case !== 'normal' && (
          <p className="border-t border-line pt-3 text-[13px] text-dim">
            {copy.verdict.heard}: {v.description}
          </p>
        )}

        {v.foreign_text && (
          <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px]">
            <div className="flex items-start justify-between gap-3">
              <p className="text-dim">{copy.verdict.foreign}</p>
              <button
                type="button"
                onClick={() => setShowForeign((s) => !s)}
                className="-my-2 min-h-12 shrink-0 text-accent"
              >
                {showForeign ? copy.verdict.hide : copy.verdict.show}
              </button>
            </div>
            {showForeign && <p className="mt-1 text-mute line-through decoration-mute/60">{v.foreign_text}</p>}
          </div>
        )}

        <p className="text-[13px] text-mute">
          {v.session_id} · {dateTimeRu(v.checked_at)} · {copy.verdict.model} {v.model_version}
        </p>
      </div>
    </section>
  )
}
