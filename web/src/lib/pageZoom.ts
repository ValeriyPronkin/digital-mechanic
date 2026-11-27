// How the manual page is sized in its sheet. No imports: the unit tests load this module in Node as it is.
//
// The scale is the page's width in widths of the sheet. On a phone the sheet is as wide as the screen: the
// page opens enlarged until the marked line reads, and a tap goes to the whole page (one width, which a
// phone's height holds) and back. On a wide screen the sheet is a panel of 480 to 720 px beside the answer:
// a page fitted to its width already reads, so it opens that way, never cut on the right; a click enlarges
// it twice at the point clicked, and the next one shows the whole page, fitted to the panel's height.

export const TAP_ZOOM = 2.2 // a tap on a phone, on a page that has no marked line
export const CLICK_ZOOM = 2 // a click on a wide panel
export const MAX_ZOOM = 4

/** The scale a page opens at. `reading` is the scale at which its marked line reads, null without a mark. */
export function openingScale(wide: boolean, reading: number | null): number {
  return wide ? 1 : (reading ?? 1)
}

/** The scale at which the whole page is seen. `ratio` is the page's height over its width; the view is
 *  what the sheet shows of the page, less the strip with the quote. On a phone it is one width, as it was. */
export function wholeScale(wide: boolean, viewWidth: number, viewHeight: number, ratio: number): number {
  if (!wide || !(viewWidth > 0) || !(viewHeight > 0) || !(ratio > 0)) return 1
  return Math.min(1, viewHeight / (viewWidth * ratio))
}

/** The scale after a tap or a click: out to the whole page from anything larger than one width, in from
 *  anything else. */
export function nextScale(wide: boolean, scale: number, reading: number | null, whole: number): number {
  if (scale > 1) return whole
  return wide ? CLICK_ZOOM : (reading ?? TAP_ZOOM)
}
