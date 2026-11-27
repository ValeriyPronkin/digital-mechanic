// The card of a check shows once, first, whether its quick request or the chat stream brings it. `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { Block, VerdictBlock } from '../src/api.ts'
import { shownVerdict, withVerdict } from '../src/lib/verdict.ts'

const card = (session_id: string, headline = 'Неисправность'): VerdictBlock =>
  ({ kind: 'verdict', session_id, headline }) as unknown as VerdictBlock
const guide = { kind: 'guide' } as Block

test('a card that comes first stands above the answer', () => {
  assert.deepEqual(withVerdict([], card('S-1')), [card('S-1')])
  // the quick request lost the race: the card still goes above what the stream already brought
  assert.deepEqual(withVerdict([guide], card('S-1')), [card('S-1'), guide])
})

test('the same check twice is one card, replaced where it stands', () => {
  const once = withVerdict([card('S-1', 'старая'), guide], card('S-1', 'из чата'))
  assert.equal(once.length, 2)
  assert.equal((once[0] as VerdictBlock).headline, 'из чата')
})

test('a card is asked for only when this check has none on the screen', () => {
  assert.equal(shownVerdict([[guide], [card('S-1')]], 'S-1'), true)
  assert.equal(shownVerdict([[card('S-1')]], 'S-2'), false) // another check picked: its card is new
  assert.equal(shownVerdict([], 'S-1'), false)
})
