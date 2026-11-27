import { useId, useState, type ReactNode } from 'react'

/** A short explanation behind a link («Что значат цифры»), or behind a «?» when the link would be longer
 *  than what it explains. Closed by default, so a screen read every day is not longer; one tap opens it in
 *  place, under the line, in small text. The tap area is 44 px high. */
export function Explain({ label, icon = false, children }: { label: string; icon?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={icon ? label : undefined}
        title={icon ? label : undefined}
        onClick={() => setOpen(!open)}
        className={
          icon
            ? "relative inline-grid size-[22px] place-items-center rounded-full border border-line text-[12px] leading-none text-accent before:absolute before:-inset-[11px] before:content-[''] hover:border-accent aria-expanded:border-accent"
            : "relative text-[13px] text-accent before:absolute before:-inset-y-3 before:inset-x-0 before:content-[''] hover:underline"
        }
      >
        {icon ? '?' : label}
      </button>
      {open && (
        <div id={id} role="note" className="basis-full space-y-1 text-[13px] leading-[1.4] text-dim">
          {children}
        </div>
      )}
    </>
  )
}
