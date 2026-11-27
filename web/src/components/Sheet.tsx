import { useEffect, useRef, type ReactNode } from 'react'
import { copy } from '../copy'
import { boxAt, focusable, holds } from '../lib/ui'

/** From 900 px a sheet is a panel beside the thread, which stays readable and undimmed (index.css). */
const beside = () => window.matchMedia('(min-width: 900px)').matches
/** The scrolled thread of the vehicle screen, if the point is on what it shows. */
function threadAt(x: number, y: number): HTMLElement | null {
  const thread = document.querySelector<HTMLElement>('[data-thread]')
  return thread && holds(thread.getBoundingClientRect(), x, y) ? thread : null
}
/** A source chip of the thread under a point of the screen. A modal sheet makes the page behind it inert,
 *  and hit testing skips what is inert (`elementsFromPoint` returns the dialog alone), so the chips are
 *  found by their boxes: the drawn chip with the 7,5 px of its tap area above and below. A chip that is
 *  scrolled out of the thread's view is not under the point. */
function chipAt(x: number, y: number): HTMLElement | null {
  const chips = [...(threadAt(x, y)?.querySelectorAll<HTMLElement>('[data-chip]') ?? [])]
  const at = boxAt(
    chips.map((chip) => chip.getBoundingClientRect()),
    x,
    y,
    7.5,
  )
  return at < 0 ? null : chips[at]
}
// A chip that was pressed through the side of an open sheet: it opens the next sheet, and that sheet, not
// the one it replaces, gives focus back to it.
let handover: HTMLElement | null = null

// The control that was pressed last, anywhere on the page. A sheet opens some time after the press
// that asked for it, and not every browser gives focus to a button that is clicked (Safari does not),
// so `document.activeElement` alone does not say what opened the sheet.
let pressed: HTMLElement | null = null
if (typeof document !== 'undefined') {
  document.addEventListener(
    'pointerdown',
    (e) => {
      const at =
        e.target instanceof Element ? e.target.closest<HTMLElement>('button, a, input, textarea, summary') : null
      if (!at?.closest('dialog')) pressed = at // a press inside a sheet did not open it
    },
    true,
  )
}

/** A native modal dialog: focus trap and Escape come from the browser. Bottom sheet on a phone, side panel on a wide screen.
 *  `open` can go false and true again while the sheet stays mounted (the ticket under an opened manual
 *  page): its content is kept, and it comes back at the scroll offset it had, with focus on the control
 *  that was used last. Neither is left to the browser: not every one keeps the offset of a closed dialog.
 *
 *  When the sheet is gone for good (Esc, the cross, a tap outside, its own buttons: every way ends in its
 *  unmounting), focus goes back to the control that opened it. If that control is gone too («Создать
 *  заявку» is, once there is a draft), `focusAfter` names the next best place. */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  focusAfter,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  focusAfter?: () => HTMLElement | null
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const offset = useRef(0) // where the content was scrolled to when the sheet was last hidden
  const used = useRef<HTMLElement | null>(null) // the control tapped last, e.g. the chip that opened a page
  // What had focus, or was pressed, when the sheet first opened; `undefined` until then. A sheet that comes
  // back from under a page keeps the opener it had.
  const opener = useRef<HTMLElement | null | undefined>(undefined)
  const after = useRef(focusAfter)
  useEffect(() => {
    after.current = focusAfter
  })

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (opener.current === undefined) {
        const focused = document.activeElement
        opener.current = handover ?? (focused instanceof HTMLElement && focused !== document.body ? focused : pressed)
        handover = null
      }
      dialog.showModal()
      // Beside the panel the thread is narrower and its text has wrapped anew: the sentence whose chip was
      // pressed is brought back into view.
      if (beside())
        (opener.current?.closest<HTMLElement>('p, li') ?? opener.current)?.scrollIntoView({ block: 'nearest' })
      if (scroller.current) scroller.current.scrollTop = offset.current
      // Back from under a page: focus returns to the control that opened it. A first opening focuses the
      // sheet itself, so no control shows a focus ring until the keyboard is used.
      if (used.current?.isConnected) used.current.focus({ preventScroll: true })
      else dialog.focus()
    }
    if (!open && dialog.open) {
      offset.current = scroller.current?.scrollTop ?? 0 // read while the sheet is still shown
      dialog.close()
    }
  }, [open])

  useEffect(
    () => () => {
      if (handover) return // a chip pressed through the side of this sheet opens the next one, which owns the focus
      // A page opened from inside the ticket sheet, closed on a browser that does not focus a clicked button:
      // this cleanup focuses the page's opener, which is the stale opener of the ticket sheet, and the
      // ticket sheet's own effect then focuses its chip. The right one wins only because the effects of a
      // commit run after its cleanups.
      const to = focusable([opener.current, after.current?.()])
      to?.focus({ preventScroll: true })
      if (beside()) to?.scrollIntoView({ block: 'nearest' }) // the thread is wide again and has wrapped anew
    },
    [],
  )

  return (
    <dialog
      ref={ref}
      tabIndex={-1}
      className="sheet"
      onClose={onClose}
      onClick={(e) => {
        if (e.target !== ref.current) {
          used.current = (e.target as HTMLElement).closest<HTMLElement>('button, a, input, summary')
          return
        }
        // A press beside the sheet. On another source chip of the thread it opens that page: the thread is
        // in full view there, and a press that only closed the open page would read as a press that did
        // nothing. Anywhere else it closes the sheet, as a tap on the dimmed page does on a phone.
        const chip = beside() ? chipAt(e.clientX, e.clientY) : null
        if (!chip) return onClose()
        handover = chip
        // A programmatic click, on purpose, on an element the modal dialog has made inert: no press of
        // the user's can reach it (which is why the chip had to be found by its box), and `click()`
        // still runs its handler. Not to be replaced by anything that needs the chip to be live.
        chip.click()
        window.setTimeout(() => {
          if (handover !== chip) return // the next sheet took it
          handover = null
          if (ref.current?.isConnected) opener.current = chip // the same sheet, moved to the chip's line
        }, 300)
      }}
      // The wheel over the thread beside the sheet scrolls the thread: the sheet is modal, so the browser
      // hands the wheel to the sheet, which passes it on.
      onWheel={(e) => {
        if (e.target !== ref.current || !beside()) return
        threadAt(e.clientX, e.clientY)?.scrollBy({ top: e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY })
      }}
    >
      <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[17px] font-semibold">{title}</h2>
          {subtitle && <div className="mt-0.5 text-[13px] text-dim">{subtitle}</div>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={copy.page.close}
          className="-mr-2 grid size-12 shrink-0 place-items-center rounded-lg text-dim hover:text-text"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            aria-hidden
          >
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        </button>
      </header>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {children}
      </div>
      {footer && (
        <footer className="border-t border-line p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">{footer}</footer>
      )}
    </dialog>
  )
}
