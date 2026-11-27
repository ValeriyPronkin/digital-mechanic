import type { Passport } from '../api.ts'
import { num, plural } from './format.ts'

const NBSP = ' '
const rub = (x: number) => `${num(x, x > 0 && x < 0.01 ? 4 : 2)}${NBSP}₽`

/** Our request passport (issue #31) as rows of words for the action log: no JSON on the screen.
 *  `fragments` — what went to the model and whether the answer used it; `calls` — each model call with its
 *  tokens and price; `total` — the price by area and the share of the context the answer did not use. */
export function passportRows(p: Passport) {
  const fragments = p.searches.flatMap((s) =>
    s.fragments.map((f) => ({
      label: `${f.manual}, стр.${NBSP}${f.pdf_page}`,
      tokens: `≈${f.tokens}${NBSP}${plural(f.tokens, ['токен', 'токена', 'токенов'])}`,
      used: f.used,
      why: f.why_in ?? null, // why the page is in the context; null in older passports
      whyOut: f.used ? null : (f.why_out ?? null), // why it did not go into the answer
    })),
  )
  const calls = p.llm.map((c) => ({
    label: c.name,
    tokens: `${c.tokens_in}${c.tokens_cached ? ` (из кэша ${c.tokens_cached})` : ''} / ${c.tokens_out}`,
    price: rub(c.cost_rub),
    time: `${num(c.ms / 1000)}${NBSP}с`,
  }))
  const t = p.total
  const total = [
    ['Модель', rub(t.model_rub)],
    ['Поиск по руководству', `≈${rub(t.search_rub)}`],
    ['Речь', rub(t.voice_rub)],
    ['Всего за запрос', `${rub(t.total_rub)} · ${num(t.ms / 1000)}${NBSP}с`],
    [
      'Лишний контекст',
      t.fragments_tokens
        ? `${Math.round(t.unused_share * 100)}${NBSP}% — ${t.unused_tokens} из ${t.fragments_tokens}${NBSP}${plural(t.fragments_tokens, ['токена', 'токенов', 'токенов'])} не пошли в ответ`
        : '—',
    ],
  ] as const
  // In plain words (PR #177): «Сколько стоило» — one line; the details — tokens by part, the cache, the unused share.
  // An older passport without them keeps its total line.
  const e = p.explain ?? {}
  const cost = e.cost ?? `${rub(t.total_rub)} · ${num(t.ms / 1000)}${NBSP}с`
  const details = [e.tokens, e.cached, e.unused].filter((x): x is string => !!x)
  // the unused share is said in words above: the older row would repeat it
  const shown = e.unused ? total.filter(([k]) => k !== 'Лишний контекст') : total
  return { fragments, calls, total: shown, rules: p.rules, cost, details }
}

export const passportFile = (p: Passport) => new Blob([JSON.stringify(p, null, 1)], { type: 'application/json' })
