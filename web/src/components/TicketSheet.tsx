import { useId, useRef, useState } from 'react'
import {
  ApiError,
  approveTicket,
  type SourceItem,
  type TicketItem,
  type TicketPending,
  type TicketView,
  type Urgency,
} from '../api'
import { copy } from '../copy'
import { Sheet } from './Sheet'
import { SourceChip } from './SourceChip'

type Sources = Record<string, SourceItem>
const urgencyTone = { high: 'text-stop', medium: 'text-warn', low: 'text-text' } as const

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-line px-4 py-3">
      <p className="text-[13px] text-dim">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

/** Works or parts. A line is its text, then its page and the remove control in one row; the lines of the
 *  manual it was found in open under it on a tap on the text. Folded, a work is about 100 px tall at
 *  320 px, so two of them fit the first screen of a small phone; on a wide screen the lines start open. */
function Items({
  items,
  removed,
  toggle,
  sources,
  onOpen,
}: {
  items: TicketItem[]
  removed: Set<number>
  toggle: (i: number) => void
  sources: Sources
  onOpen: (s: SourceItem) => void
}) {
  const id = useId()
  const [quoted, setQuoted] = useState<Set<number>>(
    () => new Set(window.matchMedia('(min-width: 900px)').matches ? items.map((_, i) => i) : []),
  )
  const flip = (i: number) =>
    setQuoted((open) => {
      const next = new Set(open)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  return (
    <ul className="divide-y divide-line">
      {items.map((item, i) => {
        const gone = removed.has(i)
        const open = !gone && quoted.has(i)
        return (
          <li key={i} className="py-2">
            {item.quote && !gone ? (
              // the padding and the margin cancel out: the text stays where it was, the target is 48 px
              <button
                type="button"
                aria-expanded={open}
                aria-controls={`${id}-${i}`}
                onClick={() => flip(i)}
                // `relative`: the words for a screen reader are positioned absolutely, and without a
                // positioned ancestor inside the list they are laid out against the dialog and make it scroll
                className="relative -my-1 flex min-h-12 w-full items-start justify-between gap-2 py-1 text-left"
              >
                <span>
                  {item.text}
                  <span className="sr-only">. {copy.ticket.inManual}</span>
                </span>
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={`mt-0.5 shrink-0 text-dim transition-transform ${open ? 'rotate-180' : ''}`}
                  aria-hidden
                >
                  <path d="M4 6l4 4 4-4" />
                </svg>
              </button>
            ) : (
              <p className={gone ? 'text-mute line-through' : ''}>{item.text}</p>
            )}
            <div className="flex min-h-9 items-center justify-between gap-2">
              <span className="-ml-0.5 min-w-0">
                {!gone && <SourceChip source={sources[item.source]} onOpen={onOpen} />}
              </span>
              <button
                type="button"
                onClick={() => toggle(i)}
                className="-my-1.5 min-h-12 shrink-0 px-2 text-[13px] text-accent"
              >
                {gone ? copy.ticket.restore : copy.ticket.remove}
              </button>
            </div>
            {item.quote && (
              <p id={`${id}-${i}`} hidden={!open} className="mt-1 border-l-2 border-line pl-2 text-[13px] text-dim">
                <span className="text-mute">
                  {copy.ticket.inManual}
                  {item.scanned ? `, ${copy.thread.scanned}` : ''}:{' '}
                </span>
                {item.quote}
              </p>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** The exact ticket that will go to ТОиР. Lines can be removed, not rewritten; only the button sends it.
 *  Mounted per draft (keyed by its id), so the removed lines start empty for every new draft. It stays
 *  mounted while a manual page is open over it (`hidden`), so what was removed and ticked is not lost. */
export function TicketSheet({
  pending,
  sources,
  checkLabel,
  hidden = false,
  onClose,
  onCreated,
  onOpenSource,
}: {
  pending: TicketPending
  sources: Sources
  checkLabel: string
  hidden?: boolean
  onClose: () => void
  onCreated: (ticket: TicketView) => void
  onOpenSource: (s: SourceItem) => void
}) {
  const [removedOps, setRemovedOps] = useState<Set<number>>(new Set())
  const [removedParts, setRemovedParts] = useState<Set<number>>(new Set())
  const [acknowledged, setAcknowledged] = useState(false)
  // The server proposes a priority; the mechanic may send the ticket with another. What is selected here
  // is what the button sends, and the button says so.
  const [urgency, setUrgency] = useState<Urgency>(pending.urgency.level)
  const choices = pending.urgency_choices ?? [] // a draft saved before the choice existed has none
  const chosen = choices.find((c) => c.level === urgency)
  // The choice is the last field of the sheet; the header says the priority can be changed and leads there.
  const choice = useRef<HTMLDivElement>(null)
  const warningBlock = useRef<HTMLDivElement>(null)
  const toChoice = () => {
    const group = choice.current
    if (!group) return
    // The three choices come to the top of the list with the name of their field (44 px) above them, and
    // below the warning while it sticks there: under it they would be scrolled to and still not seen.
    const covered = acknowledged ? 0 : (warningBlock.current?.offsetHeight ?? 0)
    // Only the list moves: `scrollIntoView` would also move anything else that can scroll around it.
    let list = group.parentElement
    while (list && getComputedStyle(list).overflowY !== 'auto') list = list.parentElement
    if (list) list.scrollTop += group.getBoundingClientRect().top - list.getBoundingClientRect().top - covered - 44
    group.querySelector<HTMLElement>('[aria-checked=true]')?.focus({ preventScroll: true })
  }
  const warning = pending.warning ?? [] // a draft saved before the field existed has none
  const warned = warning.length > 0
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ackId = useId()

  const toggle = (set: Set<number>, update: (s: Set<number>) => void) => (i: number) => {
    const next = new Set(set)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    update(next)
  }
  const keep = (n: number, removed: Set<number>) => [...Array(n).keys()].filter((i) => !removed.has(i))
  const keptOps = keep(pending.operations.length, removedOps)
  const keptParts = keep(pending.spare_parts.length, removedParts)
  const p = pending.payload

  const send = async () => {
    setSending(true)
    setError(null)
    try {
      onCreated(
        await approveTicket(
          pending.pending_id,
          p.vehicle_id,
          keptOps,
          keptParts,
          acknowledged,
          choices.length ? urgency : undefined,
        ),
      )
    } catch (e) {
      setError(e instanceof ApiError && e.detail ? e.detail : copy.ticket.failed)
    } finally {
      setSending(false)
    }
  }

  return (
    <Sheet
      open={!hidden}
      onClose={() => {
        if (!hidden) onClose() // closing it to show a page over it is not the mechanic closing it
      }}
      title={copy.ticket.title}
      // without the time of the check («…, 15:10»): with it the line wraps at 320 px, and the conclusion
      // below states the date and the time in full
      subtitle={
        // The priority and the way to change it sit at the right end of this line where they fit (a wide
        // screen) and on a line of their own where they do not (a phone).
        <span className="flex flex-wrap items-baseline justify-between gap-x-3 leading-[1.25]">
          <span>
            {p.vehicle_id} · {checkLabel.replace(/, \d{1,2}:\d{2}$/, '')}
          </span>
          {choices.length > 0 && (
            // a line of text with a 48 px target: the margins take back what the height adds
            <button type="button" onClick={toChoice} className="-my-4 min-h-12 text-left">
              {copy.ticket.urgency.toLowerCase()}: {copy.urgency[urgency]} ·{' '}
              <span className="text-accent">{copy.ticket.change}</span>
            </button>
          )}
        </span>
      }
      footer={
        <div className="space-y-3">
          {error && <p className="text-[13px] text-stop">{error}</p>}
          {keptOps.length === 0 && <p className="text-[13px] text-warn">{copy.ticket.needOperation}</p>}
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="min-h-12 flex-1 rounded-lg border border-line">
              {copy.ticket.cancel}
            </button>
            <button
              type="button"
              disabled={sending || keptOps.length === 0 || (warned && !acknowledged)}
              aria-describedby={warned && !acknowledged ? ackId : undefined}
              onClick={send}
              // inactive in its own colours, not at half opacity: the label stays readable (6,5:1)
              className="min-h-12 flex-[2] rounded-lg border border-accent bg-accent font-semibold text-bg disabled:border-line disabled:bg-surface-2 disabled:text-dim"
            >
              {sending ? (
                copy.ticket.sending
              ) : (
                // the priority that goes with it, on the button: it costs the list no height
                <>
                  <span className="block leading-tight">{copy.ticket.send}</span>
                  <span className="block text-[13px] leading-tight font-normal">
                    {copy.ticket.urgency.toLowerCase()}: {copy.urgency[urgency]}
                  </span>
                </>
              )}
            </button>
          </div>
        </div>
      }
    >
      {/* Why the result is preliminary, with the threshold, and the mechanic's tick: said once, here.
          Until it is ticked the block stays at the top of the list while the works scroll under it, so
          the reason the button below is inactive is always on the screen. */}
      {warned && (
        <div
          ref={warningBlock}
          className={`z-10 border-b border-line bg-surface-2 px-4 pt-1.5 pb-0.5 ${acknowledged ? '' : 'sticky top-0'}`}
        >
          <ul className="text-[13px] text-warn">
            {warning.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <label id={ackId} className="flex min-h-12 cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="size-5 shrink-0 accent-[var(--color-accent)]"
            />
            <span>{copy.ticket.warningAck}</span>
          </label>
        </div>
      )}
      <Field label={copy.ticket.operations}>
        <Items
          items={pending.operations}
          removed={removedOps}
          toggle={toggle(removedOps, setRemovedOps)}
          sources={sources}
          onOpen={onOpenSource}
        />
      </Field>
      <Field label={copy.ticket.parts}>
        {pending.spare_parts.length ? (
          <Items
            items={pending.spare_parts}
            removed={removedParts}
            toggle={toggle(removedParts, setRemovedParts)}
            sources={sources}
            onOpen={onOpenSource}
          />
        ) : (
          <p className="text-dim">{copy.ticket.noParts}</p>
        )}
      </Field>
      <Field label={copy.ticket.conclusion}>{p.conclusion}</Field>
      <Field label={copy.ticket.urgency}>
        {choices.length ? (
          <div ref={choice} className="flex gap-2 pt-1" role="radiogroup" aria-label={copy.ticket.urgency}>
            {choices.map((c) => (
              <button
                key={c.level}
                type="button"
                role="radio"
                aria-checked={urgency === c.level}
                onClick={() => setUrgency(c.level)}
                className="min-h-12 flex-1 rounded-lg border border-line px-1 text-dim aria-checked:border-accent aria-checked:bg-surface-2 aria-checked:text-text"
              >
                <span className="block leading-tight">{c.word}</span>
                {c.level === pending.urgency.level && (
                  <span className="block text-[13px] leading-tight text-dim">{copy.ticket.proposed}</span>
                )}
              </button>
            ))}
          </div>
        ) : (
          <p className={`font-semibold ${urgencyTone[pending.urgency.level]}`}>{pending.urgency.word}</p>
        )}
        {/* what the selected priority means for the vehicle: the text changes with the choice */}
        {(chosen?.action ?? pending.urgency.action) && (
          <p className="mt-2 text-[13px]" aria-live="polite">
            {chosen?.action ?? pending.urgency.action}
          </p>
        )}
        <p className="mt-2 text-[13px] text-dim">{copy.ticket.proposedWhy(pending.urgency.word)}</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-dim marker:text-mute">
          {pending.urgency.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </Field>
    </Sheet>
  )
}
