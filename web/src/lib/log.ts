// The imports name their files: the unit tests load this module in Node as it is (web/tests).
import type { SourceItem, UsageEvent } from '../api.ts'
import { copy } from '../copy.ts'
import { num, pageLabel, plural } from './format.ts'

const NBSP = '\u00a0'

/** A page number as the model may have sent it: 41 or «41». Anything else is not a page. */
function pageOf(value: unknown): number | null {
  const page =
    typeof value === 'number' ? value : typeof value === 'string' && /^\d+$/.test(value.trim()) ? +value : NaN
  return Number.isSafeInteger(page) && page >= 1 ? page : null // never a number that prints as «1e+21»
}

/** What one step of the agent was asked for, for the action log.
 *
 *  `chips` are pages the server issued a handle for: the step read them, and they open like any source.
 *  `text` is everything else, in plain words: the query, the check, and whatever the model asked for and
 *  did not get (a page out of range, a manual that is not this engine's) as «запрошено: …». The model's
 *  own request is never dressed as a citation, and only what parses is shown: a page that is not a number
 *  is left out, never printed as «NaN». */
export function stepDetail(
  input: Record<string, unknown> | undefined,
  sources: SourceItem[],
  manualNames: Record<string, string>, // manual id → the name the mechanic knows it by
): { chips: SourceItem[]; text: string | null } {
  if (!input) return { chips: [], text: null }
  if ('pages' in input || 'manual' in input) {
    const named = typeof input.manual === 'string' ? input.manual.trim() : ''
    const issued = named ? sources.filter((s) => [s.manual_id, s.short, s.designation, s.chip].includes(named)) : []
    const asked = Array.isArray(input.pages) ? input.pages : []
    const pages = [...new Set(asked.map(pageOf).filter((page) => page !== null))]
    const chips = pages.flatMap((page) => issued.find((s) => s.pdf_page === page) ?? [])
    const rest = pages.filter((page) => !chips.some((s) => s.pdf_page === page))
    if (chips.length > 0 && rest.length === 0) return { chips, text: null }
    const known = Object.hasOwn(manualNames, named) ? manualNames[named] : undefined // «toString» is not a manual
    const manual = known ?? issued[0]?.chip ?? issued[0]?.short ?? (named ? `«${named}»` : '')
    const what = [manual, rest.length > 0 ? pageLabel(rest.join(', ')) : ''].filter(Boolean).join(', ')
    return { chips, text: what ? copy.thread.logAsked(what) : null }
  }
  if (typeof input.query === 'string' && input.query.trim()) return { chips: [], text: `«${input.query.trim()}»` }
  if (typeof input.session_id === 'string' && input.session_id) return { chips: [], text: input.session_id }
  if (Array.isArray(input.operations)) return { chips: [], text: copy.thread.logWorks(input.operations.length) }
  return { chips: [], text: null }
}

/** The numbers of the action log: the closed row «Журнал действий · 3 шага · 0,92 ₽», and inside it the
 *  cost and the model calls. A turn that cost nothing (replayed, or no price known) shows no «0,00 ₽»:
 *  the steps stay, the cost is left out. */
export function logTotals(steps: number, usage: UsageEvent[]) {
  const cost = usage.reduce((sum, u) => sum + u.cost_rub, 0)
  const tokens = usage.reduce(
    (sum, u) => sum + u.input_tokens + u.cache_read_tokens + u.cache_write_tokens + u.output_tokens,
    0,
  )
  const price = num(cost) === num(0) ? null : `${num(cost)}${NBSP}₽`
  const models = [...new Set(usage.map((u) => u.model.replace('anthropic/', '')))].join(', ')
  const calls =
    usage.length > 0
      ? [
          `${usage.length} ${plural(usage.length, copy.thread.logCalls)}`,
          `${tokens.toLocaleString('ru-RU')} ${plural(tokens, copy.thread.logTokens)}`,
          models,
        ]
          .filter(Boolean)
          .join(' · ')
      : null
  const closed = [copy.thread.log, steps > 0 && `${steps}${NBSP}${plural(steps, copy.thread.logSteps)}`, price]
  return { closed: closed.filter(Boolean).join(' · '), price, calls }
}
