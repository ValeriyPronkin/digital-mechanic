import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type TouchEvent } from 'react'
import { ApiError, getPage, type PageMark, type PageView, type SourceItem } from '../api'
import { copy } from '../copy'
import { sourceLabel } from '../lib/format'
import { MAX_ZOOM, nextScale, openingScale, wholeScale } from '../lib/pageZoom'
import { Sheet } from './Sheet'

/** `view` null: the page could not be opened, and `why` says so in the server's words when it gave any. */
type Loaded = { page: number; view: PageView | null; why?: string }

const LINE_PX = 18 // the marked line on screen: text of about 16 px
/** From 900 px the sheet is a panel beside the thread (index.css), and the page is sized for it. */
const widePanel = () => window.matchMedia('(min-width: 900px)').matches
const MARGIN = 24 // kept around the marked line when it is longer than the screen
const IMAGE_WAIT_MS = 8_000 // a page image not in by then: its text is shown until the image comes

/** A point of the page (fractions of its sides) and where in the scrolled area it goes (px from its corner). */
type Anchor = { fx: number; fy: number; vx: number; vy: number }
/** How the page is shown: its width in widths of the sheet (lib/pageZoom.ts), and what to bring into view. */
type Zoom = { scale: number; to: 'mark' | 'start' | Anchor }

/** The sheet's own scrolling area: the page scrolls inside it in both directions. */
function scrollerOf(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (/auto|scroll/.test(getComputedStyle(p).overflowY)) return p
  }
  return null
}

/** Scroll offset along one side: the whole marked stretch [a, b] centred when it fits into `size`, else
 *  its point `c` (the number) centred without leaving the stretch. */
function fit(a: number, b: number, c: number, size: number) {
  if (b - a + 2 * MARGIN <= size) return (a + b) / 2 - size / 2
  return Math.min(Math.max(c - size / 2, a - MARGIN), b + MARGIN - size)
}

/** What the server says when it cannot serve pages at all (503: the manuals are not connected). Other
 *  refusals carry a note for developers, not for the mechanic. */
const unavailable = (e: unknown) => (e instanceof ApiError && e.status === 503 && e.detail ? e.detail : undefined)

const spread = (t: TouchEvent) =>
  Math.hypot(t.touches[0].clientX - t.touches[1].clientX, t.touches[0].clientY - t.touches[1].clientY)

/** The manual page behind a source chip. Scoped by vehicle: a page of another engine cannot be opened.
 *  Mounted per source (keyed), so it always starts on the cited page. With a quote, the server says
 *  where that line is printed; the page opens on it, enlarged until the line reads. */
export function PageSheet({
  vehicleId,
  source,
  quote,
  scanned,
  onClose,
}: {
  vehicleId: string
  source: SourceItem
  quote?: string // the line of the cited page the server found the claim's number on
  scanned?: boolean // the quote comes from the machine reading of the page image («по скану»), as the verifier said
  onClose: () => void
}) {
  const [page, setPage] = useState(source.pdf_page)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [zoom, setZoom] = useState<Zoom | null>(null) // null until the image of this page has loaded
  const canvas = useRef<HTMLButtonElement>(null)
  const picture = useRef<HTMLImageElement>(null)
  const [broken, setBroken] = useState<string | null>(null) // the image that did not load: its text instead
  const [slow, setSlow] = useState<string | null>(null) // the image still not in after IMAGE_WAIT_MS
  const strip = useRef<HTMLDivElement>(null)
  const pinch = useRef<{ spread: number; scale: number; fx: number; fy: number } | null>(null)
  const pinchedAt = useRef(0)
  const cited = page === source.pdf_page

  useEffect(() => {
    let stale = false
    getPage(vehicleId, source.manual_id, page, cited ? quote : undefined)
      .then((view) => !stale && setLoaded({ page, view }))
      .catch((e) => !stale && setLoaded({ page, view: null, why: unavailable(e) }))
    return () => {
      stale = true
    }
  }, [vehicleId, source.manual_id, page, cited, quote])

  const current = loaded?.page === page ? loaded : null
  const view = current?.view ?? null
  const mark: PageMark | null = view?.marks[0] ?? null
  const focus = view?.focus ?? mark
  // Which of the two lines to show when nothing is marked. The verifier knows where the quote came from;
  // a caller that does not pass it on gets a guess: a quote read from the image is not in the page's own text.
  const fromScan = scanned ?? (!!quote && !!view && !view.text.replace(/\s+/g, ' ').includes(quote))

  /** The enlargement at which the marked line is LINE_PX high (a line set across the sheet: wide). */
  const lineScale = (img: HTMLImageElement, width: number) => {
    if (!mark) return null
    const thickness = Math.min(mark.w * width, (mark.h * width * img.naturalHeight) / img.naturalWidth)
    return Math.min(Math.max(LINE_PX / thickness, 1), MAX_ZOOM)
  }

  useLayoutEffect(() => {
    const el = canvas.current
    const scroller = el && scrollerOf(el)
    if (!el || !scroller || !zoom) return
    const box = el.getBoundingClientRect()
    const frame = scroller.getBoundingClientRect()
    const top = box.top - frame.top + scroller.scrollTop // of the page inside the scrolled content
    const covered = strip.current?.offsetHeight ?? 0 // the strip stays over the top of the page
    if (zoom.to === 'start') {
      scroller.scrollTo(0, 0)
    } else if (zoom.to === 'mark' && mark && focus) {
      const [w, h] = [box.width, box.height]
      const x = fit(mark.x * w, (mark.x + mark.w) * w, (focus.x + focus.w / 2) * w, scroller.clientWidth)
      const y = fit(mark.y * h, (mark.y + mark.h) * h, (focus.y + focus.h / 2) * h, scroller.clientHeight - covered)
      scroller.scrollTo(x, top + y - covered)
    } else if (zoom.to !== 'mark') {
      scroller.scrollTo(zoom.to.fx * box.width - zoom.to.vx, top + zoom.to.fy * box.height - zoom.to.vy)
    }
  }, [zoom, mark, focus])

  /** The point of the page under a point of the screen, to keep it there while the page is resized. */
  const anchorAt = (clientX: number, clientY: number): Anchor | null => {
    const el = canvas.current
    const scroller = el && scrollerOf(el)
    if (!el || !scroller) return null
    const box = el.getBoundingClientRect()
    const frame = scroller.getBoundingClientRect()
    return {
      fx: (clientX - box.left) / box.width,
      fy: (clientY - box.top) / box.height,
      vx: clientX - frame.left,
      vy: clientY - frame.top,
    }
  }

  /** A tap or a click: the whole page, or enlarged at the point (lib/pageZoom.ts). */
  const toggle = (e: MouseEvent<HTMLButtonElement>) => {
    const img = e.currentTarget.querySelector('img')
    const scroller = scrollerOf(e.currentTarget)
    if (!zoom || !img || !scroller || Date.now() - pinchedAt.current < 400) return
    const wide = widePanel()
    const covered = strip.current?.offsetHeight ?? 0 // the strip stays over the top of the page
    const whole = wholeScale(
      wide,
      scroller.clientWidth,
      scroller.clientHeight - covered,
      img.naturalHeight / img.naturalWidth,
    )
    const scale = nextScale(wide, zoom.scale, lineScale(img, scroller.clientWidth), whole)
    const byKeyboard = e.detail === 0 // no point was tapped
    const at = byKeyboard ? null : anchorAt(e.clientX, e.clientY)
    if (zoom.scale > 1) setZoom({ scale, to: at ?? 'start' })
    else setZoom({ scale, to: at ?? (mark ? 'mark' : 'start') })
  }

  const pinchStart = (e: TouchEvent) => {
    if (e.touches.length !== 2 || !zoom) return
    const [a, b] = [e.touches[0], e.touches[1]]
    const at = anchorAt((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2)
    if (at) pinch.current = { spread: spread(e), scale: zoom.scale, fx: at.fx, fy: at.fy }
  }
  const pinchMove = (e: TouchEvent) => {
    const from = pinch.current
    const scroller = canvas.current && scrollerOf(canvas.current)
    if (!from || !scroller || e.touches.length !== 2) return
    const [a, b] = [e.touches[0], e.touches[1]]
    const frame = scroller.getBoundingClientRect()
    const scale = Math.min(Math.max((from.scale * spread(e)) / from.spread, 1), MAX_ZOOM)
    const to = {
      fx: from.fx,
      fy: from.fy,
      vx: (a.clientX + b.clientX) / 2 - frame.left,
      vy: (a.clientY + b.clientY) / 2 - frame.top,
    }
    setZoom({ scale, to })
  }
  const pinchEnd = () => {
    if (pinch.current) pinchedAt.current = Date.now() // the fingers lifting is not a tap
    pinch.current = null
  }

  /** The image is in: the opening enlargement, and the page becomes visible. */
  const placed = (img: HTMLImageElement) => {
    const scroller = scrollerOf(img)
    const reading = scroller && lineScale(img, scroller.clientWidth)
    setZoom({ scale: openingScale(widePanel(), reading), to: reading ? 'mark' : 'start' })
  }

  // The page must not stay invisible when the load event is missed (an image from the cache can be in
  // before the handler on iPhone) or is late (a stand waking up): a loaded image is placed at once, and
  // while one is not in after a while its text is shown; the image replaces the text when it comes.
  const image = view?.image ?? null
  useEffect(() => {
    if (!image || zoom) return
    const img = picture.current
    if (img?.complete && img.naturalWidth > 0) {
      placed(img)
      return
    }
    const late = setTimeout(() => {
      const now = picture.current
      if (now?.complete && now.naturalWidth > 0) placed(now)
      else setSlow(image)
    }, IMAGE_WAIT_MS)
    return () => clearTimeout(late)
  }, [image, zoom]) // placed reads the current mark: it is not a dependency

  const turn = (to: number) => {
    setZoom(null)
    setPage(to)
  }

  return (
    <Sheet
      open
      tall
      onClose={onClose}
      title={sourceLabel({ short: source.short, pdf_page: page })}
      subtitle={view ? `${copy.page.of} ${view.pages}` : undefined}
      footer={
        <div className="flex gap-3">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => turn(page - 1)}
            className="min-h-12 flex-1 rounded-lg border border-line enabled:hover:bg-surface-2 disabled:opacity-40"
          >
            {copy.page.previous}
          </button>
          <button
            type="button"
            disabled={!view || page >= view.pages}
            onClick={() => turn(page + 1)}
            className="min-h-12 flex-1 rounded-lg border border-line enabled:hover:bg-surface-2 disabled:opacity-40"
          >
            {copy.page.next}
          </button>
        </div>
      }
    >
      {quote && cited && (
        <div ref={strip} className="sticky top-0 left-0 z-10 border-b border-line bg-surface">
          <div className="max-h-[28dvh] overflow-y-auto bg-accent/10 px-4 py-3">
            <p className="text-[13px] text-dim">{copy.page.quote}</p>
            <p className="mt-0.5">{quote}</p>
            {view?.image && !mark && (
              <p className="mt-1.5 text-[13px] text-dim">{fromScan ? copy.page.onScan : copy.page.notMarked}</p>
            )}
          </div>
        </div>
      )}
      {!current && <p className="p-4 text-dim">{copy.page.loading}</p>}
      {current && !view && <p className="p-4 text-dim">{current.why ?? copy.page.failed}</p>}
      {view?.image && !zoom && broken !== view.image && slow !== view.image && (
        <p className="p-4 text-dim">{copy.page.loading}</p>
      )}
      {view?.image && !zoom && broken !== view.image && slow === view.image && (
        <PageText note={copy.page.imageSlow} text={view.text} />
      )}
      {view &&
        (view.image && broken !== view.image ? (
          <button
            ref={canvas}
            type="button"
            onClick={toggle}
            onTouchStart={pinchStart}
            onTouchMove={pinchMove}
            onTouchEnd={pinchEnd}
            onTouchCancel={pinchEnd}
            aria-label={zoom && zoom.scale > 1 ? copy.page.zoomOut : copy.page.zoomIn}
            style={{ width: `${(zoom?.scale ?? 1) * 100}%` }}
            className={`relative mx-auto block touch-pan-x touch-pan-y bg-white ${zoom ? '' : 'invisible'} ${zoom && zoom.scale > 1 ? 'cursor-zoom-out' : 'cursor-zoom-in'}`}
          >
            <img
              ref={picture}
              key={view.image}
              src={view.image}
              alt={sourceLabel({ short: view.short, pdf_page: view.page })}
              onLoad={(e) => placed(e.currentTarget)}
              onError={() => setBroken(view.image)}
              className="block w-full"
            />
            {mark && (
              <span
                aria-hidden
                style={{
                  left: `${mark.x * 100}%`,
                  top: `${mark.y * 100}%`,
                  width: `${mark.w * 100}%`,
                  height: `${mark.h * 100}%`,
                }}
                className="absolute rounded-[2px] bg-accent/50 mix-blend-multiply outline-2 outline-offset-1 outline-[color-mix(in_srgb,var(--color-accent)_55%,black)]"
              />
            )}
          </button>
        ) : (
          <PageText note={view.image ? copy.page.imageFailed : copy.page.textOnly} text={view.text} />
        ))}
    </Sheet>
  )
}

/** The page's own text, when there is no image of it to show (yet). */
function PageText({ note, text }: { note: string; text: string }) {
  return (
    <div className="p-4">
      <p className="mb-3 text-[13px] text-mute">{note}</p>
      <pre className="overflow-x-auto font-mono text-[12px] leading-[1.5] whitespace-pre text-text">{text}</pre>
    </div>
  )
}
