import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Passport } from '../src/api.ts'
import { passportRows } from '../src/lib/passport.ts'

const passport: Passport = {
  request_id: 'r1',
  searches: [
    {
      by: 'код',
      engine: 'ЯМЗ-236М2',
      queries: ['зазор клапанов'],
      found: 2,
      fragments: [
        { ref: 'R1', manual: 'РК ЯМЗ-236', pdf_page: 270, section: '6.4', tokens: 120, used: true },
        { ref: 'R2', manual: 'РЭ ЯМЗ-236М2', pdf_page: 31, section: '', tokens: 80, used: false },
      ],
    },
  ],
  llm: [
    {
      name: 'deepseek-flash',
      provider: 'deepseek',
      tokens_in: 3936,
      tokens_cached: 3712,
      tokens_out: 293,
      ms: 1900,
      cost_rub: 0.0412,
    },
  ],
  voice: { stt_seconds: 0, stt_rub: 0, tts_chars: 0, tts_rub_estimate: 0 },
  rules: ['Ответ прошёл проверки кода без правок.'],
  total: {
    model_rub: 0.0412,
    search_rub: 0.00002,
    voice_rub: 0,
    total_rub: 0.0412,
    ms: 2400,
    fragments_tokens: 200,
    unused_tokens: 80,
    unused_share: 0.4,
  },
}

test('the passport reads as rows: used and unused context, calls with tokens and price, totals by area', () => {
  const rows = passportRows(passport)
  assert.deepEqual(
    rows.fragments.map((f) => f.used),
    [true, false],
  )
  assert.match(rows.fragments[0].label, /РК ЯМЗ-236, стр. 270/)
  assert.match(rows.calls[0].tokens, /3936 \(из кэша 3712\) \/ 293/)
  assert.match(rows.calls[0].price, /0,04/)
  const total = Object.fromEntries(rows.total)
  assert.match(total['Лишний контекст'], /^40\u00a0% — 80 из 200\u00a0токенов/)
  assert.match(total['Поиск по руководству'], /0,0000/) // a sum below a kopeck keeps its digits
})
