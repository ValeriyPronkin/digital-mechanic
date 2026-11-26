import { useEffect, useRef, type ReactNode } from 'react'
import { copy } from '../copy'

/** A native modal dialog: focus trap and Escape come from the browser. Bottom sheet on a phone, side panel on a wide screen.
 *  `open` can go false and true again while the sheet stays mounted (the ticket under an opened manual
 *  page): its content is kept, and it comes back at the scroll offset it had, with focus on the control
 *  that was used last. Neither is left to the browser: not every one keeps the offset of a closed dialog. */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const offset = useRef(0) // where the content was scrolled to when the sheet was last hidden
  const used = useRef<HTMLElement | null>(null) // the control tapped last, e.g. the chip that opened a page

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
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
