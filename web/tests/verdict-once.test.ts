// The check's card once per conversation (Валерий, 27.11): later turns get a line back to it. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { Block } from '../src/api.ts'
import { shownBefore } from '../src/lib/verdict.ts'

const card = (session_id: string) => ({ kind: 'verdict', session_id }) as unknown as Block
const guide = { kind: 'guide' } as unknown as Block

test('the first card of a check is whole; the same check later is a line; another check is whole again', () => {
  const turns: Block[][] = [[card('S-0009')], [], [card('S-0009'), guide], [card('S-0010')], [card('S-0009')]]
  assert.deepEqual(
    shownBefore(turns).map((s) => [...s].sort()),
    [[], ['S-0009'], ['S-0009'], ['S-0009'], ['S-0009', 'S-0010']],
  )
})

test('two cards of one check in one turn are not hidden from each other (withVerdict keeps one anyway)', () => {
  assert.deepEqual(
    shownBefore([[card('S-1'), card('S-1')]]).map((s) => s.size),
    [0],
  )
})
