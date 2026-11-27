// The view stays with the question while its answer streams. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { anchoringWhile } from '../src/lib/scroll.ts'

test("the browser keeps the reader's place by itself, except while an answer runs", () => {
  // while it runs, anchoring would move the view down with the answer (seen in a browser: the question ends
  // 108 px above the view on a phone, 1189 px on a laptop)
  assert.equal(anchoringWhile(true), '[overflow-anchor:none]')
  // otherwise it stays on: a late ticket card above the conversation must not move the text under the eye
  assert.equal(anchoringWhile(false), '')
})
