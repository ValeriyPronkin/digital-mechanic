import { useEffect, useRef, type ReactNode } from 'react'
import { copy } from '../copy'
import { focusable } from '../lib/ui'

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
        opener.current = focused instanceof HTMLElement && focused !== document.body ? focused : pressed
      }
      dialog.showModal()
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
      const to = focusable([opener.current, after.current?.()])
      to?.focus({ preventScroll: true })
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
        if (e.target === ref.current)
          onClose() // a tap on the backdrop
        else used.current = (e.target as HTMLElement).closest<HTMLElement>('button, a, input, summary')
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
