import type { SourceItem } from '../api'
import { copy } from '../copy'
import { chipLabel } from '../lib/format'

/** The mark of a number the server found on the page. The same drawing is in the legend under an answer. */
export function CheckMark({ label }: { label?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      role={label ? 'img' : undefined}
      aria-hidden={label ? undefined : true}
      className="shrink-0"
    >
      {label && <title>{label}</title>}
      <path d="M2.5 6.5l2.5 2.5 4.5-5.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** «236.01.01 РК, стр. 41»: the reference the jury checks. A tap opens that page.
 *  The check mark means the server found the claim's numbers on this page.
 *  The chip never grows past the line it sits in: a long manual name is cut with «…», the page never is.
 *  `repeat` leaves the manual out, for a chip that cites the same manual as the chip before it.
 *  The chip is drawn 25 px high with half a pixel above and below, so a line with a chip is 26 px, as it
 *  was before the chip had a tap area, and two chips on neighbouring lines do not touch. The area that
 *  takes the tap is 40 px high: 7,5 px above and below the drawn chip, an invisible layer of the button.
 *  That layer lies under every drawn chip, so where two chips are closer than 15 px a tap on a chip
 *  still opens that chip.
 *  Sizes are in px on purpose, so the chip does not move with the spacing scale of the theme. */
export function SourceChip({
  source,
  verified = false,
  scanned = false,
  repeat = false,
  onOpen,
}: {
  source: SourceItem | undefined
  verified?: boolean
  scanned?: boolean // confirmed only by the machine reading of the page image
  repeat?: boolean
  onOpen: (s: SourceItem) => void
}) {
  if (!source) return null // a handle the server never issued is not shown as a source
  const label = chipLabel(source, repeat)
  return (
    <button
      type="button"
      onClick={() => onOpen(source)}
      title={scanned ? copy.thread.scannedHint : verified ? copy.thread.verifiedLegend : undefined}
      className="group/chip relative mx-[4px] my-[0.5px] inline-flex max-w-[calc(100%-8px)] rounded-[8px] align-middle text-[13px] leading-none text-accent before:absolute before:inset-x-0 before:-inset-y-[7.5px] before:content-['']"
    >
      <span className="relative z-[1] inline-flex min-h-[25px] max-w-full min-w-0 items-center gap-[4px] rounded-[8px] border border-line bg-surface-2 px-[8px] group-hover/chip:border-accent">
        {verified && <CheckMark label={copy.thread.verifiedLegend} />}
        {/* The comma is cut with the name, so a cut name reads «236-3902150-… стр. 39», not «…, стр. 39». */}
        <span className="flex min-w-0 gap-[0.3em] whitespace-nowrap">
          {label.manual && <span className="truncate">{label.manual}, </span>}
          <span className="shrink-0">{label.page}</span>
        </span>
        {scanned && <span className="shrink-0 whitespace-nowrap text-warn">· {copy.thread.scanned}</span>}
      </span>
    </button>
  )
}
