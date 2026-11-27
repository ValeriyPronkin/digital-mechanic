import { useState } from 'react'
import type { Passport, SourceItem, ToolTrace, UsageEvent } from '../api'
import { copy } from '../copy'
import { logTotals, stepDetail } from '../lib/log'
import { passportFile, passportRows } from '../lib/passport'
import { SourceChip } from './SourceChip'

type Sources = Record<string, SourceItem>

/** What the agent did for this answer and what it cost. Collapsed by default; the closed row already says
 *  how many steps it took and what they cost: «Журнал действий · 3 шага · 0,92 ₽».
 *  Open: each step, and under its name what it was asked for, never cut short (a long query wraps, even
 *  one with no space in it). A page the agent read is the same chip as in the answer and opens the same
 *  page; what it only asked for is plain text. */
export function ActionLog({
  tools,
  usage,
  manualNames,
  sources = {},
  onOpen,
  passport,
}: {
  tools: ToolTrace[]
  usage: UsageEvent[]
  manualNames: Record<string, string> // manual id → the name the mechanic knows it by
  sources?: Sources // the pages that were issued a handle: a page the agent read opens from the log
  onOpen?: (s: SourceItem) => void
  passport?: Passport // our request passport (#31): what went to the model, what it cost, which rules worked
}) {
  if (!tools.length && !usage.length) return null
  const totals = logTotals(tools.length, usage)
  const issued = onOpen ? Object.values(sources) : [] // with nothing to open a page with, pages are named in words
  return (
    <details className="group text-[13px] text-dim">
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 hover:text-text [&::-webkit-details-marker]:hidden">
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          className="shrink-0 transition-transform group-open:rotate-90"
          aria-hidden
        >
          <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        {totals.closed}
      </summary>
      <ol className="mb-2 space-y-1.5 border-l border-line pl-4 wrap-anywhere">
        {tools.map((t, i) => {
          const { chips, text } = stepDetail(t.input, issued, manualNames)
          return (
            <li key={i}>
              <span className={t.ok === false ? 'text-warn' : 'text-text'}>{copy.tool[t.name] ?? t.name}</span>
              {onOpen && chips.length > 0 && (
                <span className="-ml-[4px] flex flex-wrap gap-y-[14px] py-[7px]">
                  {chips.map((s, j) => (
                    <SourceChip key={s.handle} source={s} repeat={j > 0} onOpen={onOpen} />
                  ))}
                </span>
              )}
              {text && <span className="block">{text}</span>}
            </li>
          )
        })}
        {totals.calls && (
          <li className="pt-1">
            {totals.price && (
              <span className="block text-text">
                {copy.thread.logCost}: {totals.price}
              </span>
            )}
            <span className="block">{totals.calls}</span>
          </li>
        )}
        {passport && <PassportSection passport={passport} />}
      </ol>
    </details>
  )
}

/** The request passport inside the open log, in the order the mechanic reads it (Валерий, 27.11): first «Откуда
 *  ответ» — each page with why it went to the model and, when the answer did not use it, why not; then «Сколько
 *  стоило» in one line; the details (tokens by part, the cache, the unused share, the model calls, the rules) are
 *  folded behind a button — not a <details>, so the log stays one fold. The JSON is a download. */
function PassportSection({ passport }: { passport: Passport }) {
  const rows = passportRows(passport)
  const [open, setOpen] = useState(false)
  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(passportFile(passport))
    a.download = `passport-${passport.request_id ?? 'answer'}.json`
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  return (
    <li className="space-y-3 pt-2" data-passport>
      <span className="block font-semibold text-text">{copy.passport.title}</span>
      {rows.fragments.length > 0 && (
        <div>
          <span className="block text-text">{copy.passport.from}</span>
          <ul className="mt-1 space-y-1.5">
            {rows.fragments.map((f, i) => (
              <li key={i} className={f.used ? 'text-text' : 'text-mute'}>
                <span className="block">
                  {f.used ? '✓ ' : '— '}
                  {f.label} · {f.tokens}
                  {!f.why && <> · {f.used ? copy.passport.used : copy.passport.unused}</>}
                </span>
                {f.why && <span className="block text-dim">{f.why}</span>}
                {f.why && !f.used && (
                  <span className="block text-warn">{copy.passport.notUsedWhy(f.whyOut ?? copy.passport.unused)}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p>
        <span className="text-text">{copy.passport.cost}:</span> <span className="text-text">{rows.cost}</span>
      </p>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-12 text-accent underline-offset-2 hover:underline"
      >
        {open ? copy.passport.less : copy.passport.more}
      </button>
      {open && (
        <div className="space-y-2">
          {rows.details.length > 0 && (
            <ul className="space-y-0.5">
              {rows.details.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
          {rows.calls.length > 0 && (
            <div>
              <span className="block">{copy.passport.calls}</span>
              <ul className="mt-0.5 space-y-0.5">
                {rows.calls.map((c, i) => (
                  <li key={i}>
                    {c.label} · {c.tokens} · {c.time} · <span className="text-text">{c.price}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <span className="block">{copy.passport.rules}</span>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
              {rows.rules.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {rows.total.map(([k, v]) => (
              <div key={k} className="contents">
                <dt>{k}</dt>
                <dd className="text-text">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <button type="button" onClick={download} className="min-h-12 text-accent underline-offset-2 hover:underline">
        {copy.passport.download}
      </button>
    </li>
  )
}
