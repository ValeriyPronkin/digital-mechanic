// The role switch's arrow keys, the fade of a row that scrolls on, the tab's title and the ticket number
// marked up inside its sentence (pronkinnikita/digital-mechanic#112). Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  around,
  CHECKED,
  focusable,
  nextChoice,
  PRESSED,
  PRESSED_STATUS,
  scrollsFurther,
  tabTitle,
} from '../src/lib/ui.ts'

test('arrow keys move the choice inside a radiogroup and wrap at its ends', () => {
  assert.equal(nextChoice(0, 'ArrowRight', 2), 1)
  assert.equal(nextChoice(1, 'ArrowRight', 2), 0)
  assert.equal(nextChoice(0, 'ArrowLeft', 2), 1)
  assert.equal(nextChoice(1, 'ArrowLeft', 2), 0)
  assert.equal(nextChoice(0, 'ArrowDown', 3), 1)
  assert.equal(nextChoice(0, 'ArrowUp', 3), 2)
  assert.equal(nextChoice(1, 'Home', 3), 0)
  assert.equal(nextChoice(1, 'End', 3), 2)
})

test('any other key is not the radiogroup’s: Tab leaves it, Enter and Space are the button’s own', () => {
  for (const key of ['Tab', 'Enter', ' ', 'a', 'Escape']) assert.equal(nextChoice(0, key, 2), null)
  assert.equal(nextChoice(0, 'ArrowRight', 0), null)
})

test('a row fades at its right edge only while it can be scrolled further', () => {
  // 862 px of chips in a 390 px row
  assert.equal(scrollsFurther(0, 862, 390), true)
  assert.equal(scrollsFurther(300, 862, 390), true)
  assert.equal(scrollsFurther(472, 862, 390), false)
  // a fractional offset at the end, as a phone reports it, is still the end
  assert.equal(scrollsFurther(471.5, 862, 390), false)
  // a row that fits (a wide screen, where it wraps) never fades
  assert.equal(scrollsFurther(0, 720, 720), false)
})

test('the tab is named by the plate when a vehicle is open', () => {
  assert.equal(tabTitle('Цифровой механик', null), 'Цифровой механик')
  assert.equal(tabTitle('Цифровой механик', 'A427MA78'), 'A427MA78 · Цифровой механик')
})

test('a sentence is cut around the ticket number, and comes back whole when the number is not in it', () => {
  assert.deepEqual(around('Заявка TKT-0001 создана', 'TKT-0001'), ['Заявка ', 'TKT-0001', ' создана'])
  assert.deepEqual(around('Заявка создана', 'TKT-0001'), ['Заявка создана', '', ''])
  assert.deepEqual(around('Заявка создана', ''), ['Заявка создана', '', ''])
})

test('selected and pressed share one look, and none of them is the accent of the focus ring', () => {
  for (const look of [CHECKED, PRESSED, PRESSED_STATUS]) {
    assert.match(look, /border-edge/)
    assert.doesNotMatch(look, /accent/)
  }
  // a status word in red is never put on the upper fill
  assert.doesNotMatch(PRESSED_STATUS, /surface-2/)
})

test('focus goes back to what opened the sheet, or to the next best place when that is gone', () => {
  const chip = { isConnected: true, name: 'chip' }
  const gone = { isConnected: false, name: 'Создать заявку' }
  const waits = { isConnected: true, name: 'Открыть заявку' }
  const busy = { isConnected: true, disabled: true, name: 'busy' }
  assert.equal(focusable([chip, waits]), chip)
  assert.equal(focusable([gone, waits]), waits)
  assert.equal(focusable([null, undefined, waits]), waits)
  assert.equal(focusable([busy, waits]), waits)
  assert.equal(focusable([gone, null]), null)
})
