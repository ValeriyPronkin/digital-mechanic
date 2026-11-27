import type { Passport } from '../api.ts'
import { num } from './format.ts'

const NBSP = ' '
const rub = (x: number) => `${num(x, x > 0 && x < 0.01 ? 4 : 2)}${NBSP}₽`

/** Our request passport (issue #31) as rows of words for the action log: no JSON on the screen.
 *  `fragments` — what went to the model and whether the answer used it; `calls` — each model call with its
 *  tokens and price; `total` — the price by area and the share of the context the answer did not use. */
export function passportRows(p: Passport) {
  const fragments = p.searches.flatMap((s) =>
    s.fragments.map((f) => ({
      label: `${f.manual}, стр.${NBSP}${f.pdf_page}`,
      tokens: `≈${f.tokens}${NBSP}ток.`,
      used: f.used,
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
        ? `${Math.round(t.unused_share * 100)}% — ${t.unused_tokens} из ${t.fragments_tokens} ток. не пошли в ответ`
        : '—',
    ],
  ] as const
  return { fragments, calls, total, rules: p.rules }
}

export const passportFile = (p: Passport) => new Blob([JSON.stringify(p, null, 1)], { type: 'application/json' })
