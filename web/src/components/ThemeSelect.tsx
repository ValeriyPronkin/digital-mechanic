import { useState } from 'react'
import { copy } from '../copy'
import { saveChoice, storedChoice, THEMES, type ThemeChoice } from '../lib/theme'

/** «Тема: тёмная ▾» in the fleet header, on the line of the product's name. A native select: on a phone it
 *  is the system's own picker, big enough for a thumb. The line is 13 px; the select is 40 px tall and
 *  reaches into the header's padding above and the gap below, so the header does not grow and three
 *  vehicles still show at 320×568. */
export function ThemeSelect() {
  const [choice, setChoice] = useState<ThemeChoice>(storedChoice)
  return (
    <label className="relative -my-[14px] flex min-h-10 items-center gap-1.5 text-[13px] text-dim hover:text-text">
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden
        className="shrink-0"
      >
        {/* half a circle filled: dark and light */}
        <circle cx="8" cy="8" r="6" />
        <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" stroke="none" />
      </svg>
      <span className="sr-only">{copy.theme.label}</span>
      <select
        value={choice}
        onChange={(e) => {
          const next = e.target.value as ThemeChoice
          setChoice(next)
          saveChoice(next)
        }}
        className="min-h-10 cursor-pointer appearance-none bg-transparent pr-4 text-inherit"
      >
        {THEMES.map((t) => (
          <option key={t} value={t}>
            {copy.theme.choice[t]}
          </option>
        ))}
      </select>
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
        className="pointer-events-none absolute right-0"
      >
        <path d="M3 4.5l3 3 3-3" />
      </svg>
    </label>
  )
}
