// How the manual page is sized on a phone and on a wide panel, and which chip a press beside a sheet lands
// on (pronkinnikita/digital-mechanic#115). Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { CLICK_ZOOM, nextScale, openingScale, TAP_ZOOM, wholeScale } from '../src/lib/pageZoom.ts'
import { boxAt, holds } from '../src/lib/ui.ts'

const A4 = 1984 / 1400 // the page images of the manuals

test('on a phone the page opens at the size its marked line reads, as it did', () => {
  assert.equal(openingScale(false, 1.75), 1.75)
  assert.equal(openingScale(false, null), 1) // no marked line: one width
})

test('on a wide panel the page opens fitted to the panel’s width, never cut on the right', () => {
  // at 900 px the panel is 480 px and the marked line would ask for 1,42 widths: 202 px of every line off screen
  assert.equal(openingScale(true, 1.42), 1)
  assert.equal(openingScale(true, 1.07), 1)
  assert.equal(openingScale(true, null), 1)
})

test('a phone’s whole page is one width; a wide panel’s is fitted to its height', () => {
  assert.equal(wholeScale(false, 390, 600, A4), 1)
  // a 560 px panel shows 647 px of the page: 560 × 1,417 = 794 px tall at one width
  const whole = wholeScale(true, 560, 647, A4)
  assert.ok(Math.abs(whole - 647 / (560 * A4)) < 1e-9)
  assert.ok(whole < 1)
  // a view taller than the page: never larger than one width
  assert.equal(wholeScale(true, 480, 2000, A4), 1)
  // nothing measured yet: one width, not NaN or zero
  assert.equal(wholeScale(true, 0, 647, A4), 1)
  assert.equal(wholeScale(true, 560, 0, A4), 1)
  assert.equal(wholeScale(true, 560, 647, Number.NaN), 1)
})

test('a tap on a phone goes between the reading size and the whole page', () => {
  assert.equal(nextScale(false, 1.75, 1.75, 1), 1) // out
  assert.equal(nextScale(false, 1, 1.75, 1), 1.75) // back in
  assert.equal(nextScale(false, 1, null, 1), TAP_ZOOM) // no marked line
  assert.equal(nextScale(false, 3.1, 1.75, 1), 1) // after a pinch: out
})

test('a click on a wide panel enlarges twice, the next one shows the whole page, then twice again', () => {
  const whole = 0.81
  assert.equal(nextScale(true, 1, 1.07, whole), CLICK_ZOOM) // from the opening size
  assert.equal(nextScale(true, CLICK_ZOOM, 1.07, whole), whole)
  assert.equal(nextScale(true, whole, 1.07, whole), CLICK_ZOOM)
  assert.equal(nextScale(true, 1, null, whole), CLICK_ZOOM) // a page without a marked line
})

const chips = [
  { left: 100, top: 100, right: 300, bottom: 125 }, // a chip on one line
  { left: 100, top: 132, right: 180, bottom: 157 }, // the chip of the next line, 7 px below
]

test('a press lands on the chip under it, with the tap area above and below the drawn chip', () => {
  assert.equal(boxAt(chips, 200, 110, 7.5), 0)
  assert.equal(boxAt(chips, 200, 95, 7.5), 0) // 5 px above the drawn chip
  assert.equal(boxAt(chips, 200, 95), -1) // without the tap area it is a miss
  assert.equal(boxAt(chips, 400, 110, 7.5), -1) // to the right of it
  assert.equal(boxAt(chips, 200, 80, 7.5), -1)
})

test('between two chips on neighbouring lines the nearer one takes the press', () => {
  assert.equal(boxAt(chips, 150, 127, 7.5), 0) // 2 px under the first, 5 px over the second
  assert.equal(boxAt(chips, 150, 130, 7.5), 1)
  assert.equal(boxAt(chips, 250, 130, 7.5), 0) // the second chip does not reach this far right
  assert.equal(boxAt([], 150, 127, 7.5), -1)
})

test('a point is on a box up to its edges', () => {
  const thread = { left: 0, top: 57, right: 720, bottom: 615 }
  assert.equal(holds(thread, 10, 57), true)
  assert.equal(holds(thread, 720, 615), true)
  assert.equal(holds(thread, 721, 300), false)
  assert.equal(holds(thread, 300, 640), false) // the composer under the thread
})

test('the boxes may be DOMRects, whose sides are getters of the prototype and not their own properties', () => {
  class Rect {
    #sides: [number, number, number, number]
    constructor(...sides: [number, number, number, number]) {
      this.#sides = sides
    }
    get left() {
      return this.#sides[0]
    }
    get top() {
      return this.#sides[1]
    }
    get right() {
      return this.#sides[2]
    }
    get bottom() {
      return this.#sides[3]
    }
  }
  const rects = [new Rect(100, 100, 300, 125), new Rect(100, 132, 180, 157)]
  assert.deepEqual({ ...rects[0] }, {}) // what a spread of such a box gives
  assert.equal(boxAt(rects, 200, 95, 7.5), 0)
  assert.equal(boxAt(rects, 150, 130, 7.5), 1)
  assert.equal(holds(rects[0], 200, 110), true)
})

// «Что проверить»: every line of the list ends in a chip. Lines are 33 px apart and a chip is 25 px high, so
// the 7,5 px tap areas of neighbouring chips share the 8 px between them.
const list = [0, 1, 2, 3].map((line) => ({ left: 300, top: 100 + 33 * line, right: 360, bottom: 125 + 33 * line }))

test('in a list where every line ends in a chip, a press takes the nearer chip, not the upper one', () => {
  // between the first chip (bottom 125) and the second (top 133): both tap areas hold these points
  assert.equal(boxAt(list, 330, 127, 7.5), 0) // 2 px under the first
  assert.equal(boxAt(list, 330, 131, 7.5), 1) // 2 px over the second
  assert.equal(boxAt(list, 330, 132.4, 7.5), 1) // still in the first chip's tap area, and the second's press
  // on a drawn chip the press is that chip's, although the chip above reaches 7,5 px into it
  assert.equal(boxAt(list, 330, 134, 7.5), 1)
  assert.equal(boxAt(list, 330, 199 + 3, 7.5), 3)
})

test('the order of the boxes does not decide which chip takes a press', () => {
  const reversed = [...list].reverse()
  for (const y of [127, 131, 134, 160, 164, 193, 197]) {
    const forward = list[boxAt(list, 330, y, 7.5)]
    const backward = reversed[boxAt(reversed, 330, y, 7.5)]
    assert.equal(forward, backward, `at y = ${y}`)
  }
})

test('nearer is counted down the screen: a long chip pressed near its end is not lost to a short one below', () => {
  const long = { left: 100, top: 100, right: 400, bottom: 125 } // «236-3902150-Б РЭ, стр. 54»
  const short = { left: 340, top: 133, right: 400, bottom: 158 } // «стр. 48» on the next line
  // on the long chip, 5 px from its bottom: its own middle is 7,5 px away, the short chip's is 25,5 px away
  // down the screen, though the short chip's centre is the closer one across
  assert.equal(boxAt([long, short], 370, 120, 7.5), 0)
  assert.equal(boxAt([short, long], 370, 120, 7.5), 1)
})

test('exactly midway between two chips the one whose centre is nearer across takes the press', () => {
  const left = { left: 100, top: 100, right: 300, bottom: 125 }
  const right = { left: 200, top: 133, right: 400, bottom: 158 }
  // y = 129 is 16,5 px from both middles; x = 290 is 90 px from the first centre and 10 px from the second
  assert.equal(boxAt([left, right], 290, 129, 7.5), 1)
  assert.equal(boxAt([right, left], 290, 129, 7.5), 0)
  assert.equal(boxAt([left, right], 210, 129, 7.5), 0)
})
