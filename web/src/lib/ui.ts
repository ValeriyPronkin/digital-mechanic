// Small decisions of the interface that are worth a test. No imports: the unit tests load this module in
// Node as it is (web/tests).

/** Selected, checked or pressed: one quiet look for every such control, a fill one step up from its ground
 *  and the `--edge` border. It is never the cyan ring: that one means keyboard focus (`:focus-visible`) and
 *  nothing else. The class names are spelled out whole so that Tailwind finds them. */
export const CHECKED = 'aria-checked:border-edge aria-checked:bg-surface-2 aria-checked:text-text'
export const PRESSED = 'aria-pressed:border-edge aria-pressed:bg-surface-2 aria-pressed:text-text'
/** The same look for a control whose label is a status word in its colour: red text measures 4,44:1 on
 *  `--surface-2` and 4,85:1 on `--surface`, so the fill is the lower one. */
export const PRESSED_STATUS = 'aria-pressed:border-edge aria-pressed:bg-surface'

/** A radiogroup with one tab stop: which option an arrow key moves to from option `index` of `count`, or
 *  null when the key is not one of the group's. The ends wrap, and Home and End go to the first and the
 *  last, as in a native group of radio buttons. */
export function nextChoice(index: number, key: string, count: number): number | null {
  if (count < 1) return null
  if (key === 'ArrowRight' || key === 'ArrowDown') return (index + 1) % count
  if (key === 'ArrowLeft' || key === 'ArrowUp') return (index - 1 + count) % count
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return null
}

/** Is there more of a row to the right of what is shown? Half a pixel of rounding is not «more»: a row at
 *  its end must lose the fade that says it goes on. */
export function scrollsFurther(scrollLeft: number, scrollWidth: number, clientWidth: number): boolean {
  return scrollWidth - clientWidth - scrollLeft > 1
}

/** The title of the browser tab: the plate first when a vehicle is open, so that two tabs can be told apart. */
export function tabTitle(product: string, vehicleId: string | null): string {
  return vehicleId ? `${vehicleId} · ${product}` : product
}

/** A sentence cut around one of its parts, to mark that part up: «Заявка », «TKT-0001», « создана». Without
 *  the part in it the sentence comes back whole, with nothing to mark. */
export function around(sentence: string, part: string): [before: string, part: string, after: string] {
  const at = part ? sentence.indexOf(part) : -1
  if (at < 0) return [sentence, '', '']
  return [sentence.slice(0, at), part, sentence.slice(at + part.length)]
}

/** Where focus goes when a sheet is gone: the first candidate that is still on the page and can take
 *  focus. The control that opened the sheet comes first; it may have left the page meanwhile («Создать
 *  заявку» does, once there is a draft) or be disabled while an answer runs. */
export function focusable<T extends { isConnected: boolean; disabled?: boolean }>(
  candidates: (T | null | undefined)[],
): T | null {
  return candidates.find((el): el is T => !!el && el.isConnected && !el.disabled) ?? null
}
