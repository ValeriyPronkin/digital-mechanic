import { useEffect, useId, useRef, useState } from 'react'
import { setOutcome, type Outcome, type TicketView } from '../api'
import { copy } from '../copy'
import { dateTimeRu, sourceLabel } from '../lib/format'
import { noteChanged as differs, typedAfterSave } from '../lib/tickets'
import { around, PRESSED } from '../lib/ui'

const OUTCOMES: Outcome[] = ['confirmed', 'not_confirmed', 'other_fault']

/** A ticket ТОиР accepted: its number, then what the inspection found, then what was sent. The outcome
 *  is the label the acoustic model's owners need, so it sits right under the number; the works, the
 *  parts and the pages the mechanic has already approved fold away. */
export function TicketCard({ ticket, onChange }: { ticket: TicketView; onChange: (t: TicketView) => void }) {
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  // What the mechanic typed and has not saved; null while the field shows the stored note. The field is
  // never a copy of the ticket: the card can be drawn from the thread, which holds the ticket as it was
  // when created, before the ticket with its note arrives from the server.
  const [typed, setTyped] = useState<string | null>(null)
  const typedNow = useRef<string | null>(null) // the same, as it is this instant: a save reads it when it returns
  const type = (value: string | null) => {
    typedNow.current = value
    setTyped(value)
  }
  const title = useId()
  const savedLine = useRef<HTMLParagraphElement>(null)
  const focusSaved = useRef(false)
  const p = ticket.payload
  const stored = ticket.outcome_note ?? ''
  const noteChanged = differs(typed, stored)

  // The note is sent only when the mechanic changed it: a tap on another outcome keeps what is stored
  // (the server leaves the note alone when none is sent) and still carries what was typed and not saved.
  const save = async (outcome: Outcome, fromNote = false) => {
    setSaving(true)
    setFailed(false)
    try {
      const saved = await setOutcome(ticket.id, outcome, noteChanged && typed !== null ? typed.trim() : undefined)
      onChange(saved)
      // The mechanic may have typed on while the save was on its way: that text is not what was saved, so it
      // stays in the field with «Сохранить» beside it, and the focus stays with him.
      const rest = typedAfterSave(typedNow.current, saved.outcome_note)
      type(rest)
      focusSaved.current = fromNote && rest === null
    } catch {
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }
  // «Сохранить» leaves the screen once the note is saved; focus goes to the line that says so, not to the page.
  useEffect(() => {
    if (focusSaved.current && savedLine.current) {
      savedLine.current.focus()
      focusSaved.current = false
    }
  })

  const [before, number, rest] = around(copy.ticket.created(ticket.ticket_id), ticket.ticket_id)
  return (
    <section className="relative overflow-hidden rounded-xl border border-line bg-surface">
      <div className="absolute inset-y-0 left-0 w-1 bg-accent" aria-hidden />
      <div className="space-y-2 pt-4 pr-4 pb-1 pl-5">
        {/* one click takes the whole number: a double click on «TKT-0001» selected «0001» */}
        <h2 className="text-[17px] font-semibold">
          {before}
          <span className="select-all">{number}</span>
          {rest}
        </h2>
        <p className="text-[13px] text-dim">
          {dateTimeRu(ticket.created_at)} · {copy.ticket.urgency.toLowerCase()}: {copy.urgency[p.urgency]}
          {/* the mechanic sent it with another priority than the server proposed */}
          {ticket.urgency_proposed &&
            ticket.urgency_proposed !== p.urgency &&
            ` (${copy.ticket.proposed} ${copy.urgency[ticket.urgency_proposed]})`}
        </p>

        <div className="space-y-2 border-t border-line pt-3">
          <p id={title} className="text-[13px] text-dim">
            {copy.ticket.outcomeTitle}
          </p>
          <div className="flex flex-wrap gap-2" role="group" aria-labelledby={title}>
            {OUTCOMES.map((o) => (
              <button
                key={o}
                type="button"
                disabled={saving}
                aria-pressed={ticket.outcome === o}
                onClick={() => save(o)}
                className={`min-h-12 grow rounded-lg border border-line px-3 text-[13px] text-dim enabled:hover:text-text disabled:opacity-50 ${PRESSED}`}
              >
                {copy.ticket.outcome[o]}
              </button>
            ))}
          </div>
          {ticket.outcome && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (ticket.outcome) void save(ticket.outcome, true)
              }}
            >
              <label className="block">
                {/* 8 px under the label: the focus ring of the field takes 4 of them */}
                <span className="mb-2 block text-[13px] text-dim">{copy.ticket.outcomeNote}</span>
                <textarea
                  value={typed ?? stored}
                  onChange={(e) => type(e.target.value)}
                  rows={2}
                  maxLength={500}
                  className="block min-h-12 w-full resize-none rounded-lg border border-line bg-surface-2 px-3 py-3"
                />
              </label>
              {noteChanged && (
                <button
                  type="submit"
                  disabled={saving}
                  className="min-h-12 w-full rounded-lg border border-accent px-3 font-semibold text-accent disabled:opacity-50"
                >
                  {copy.ticket.outcomeNoteSave}
                </button>
              )}
            </form>
          )}
          {failed ? (
            <p role="status" className="text-[13px] text-warn">
              {copy.ticket.outcomeFailed}
            </p>
          ) : (
            ticket.outcome &&
            !noteChanged && (
              <p ref={savedLine} tabIndex={-1} role="status" className="text-[13px] text-dim outline-none">
                {copy.ticket.outcomeSaved}
              </p>
            )
          )}
        </div>

        <details className="group border-t border-line">
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 text-[13px] text-dim [&::-webkit-details-marker]:hidden">
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              className="transition-transform group-open:rotate-90"
              aria-hidden
            >
              <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {copy.ticket.contents}
          </summary>
          <div className="space-y-2 pb-3">
            <ul className="list-disc space-y-1 pl-5 marker:text-mute">
              {p.operations.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
            {p.spare_parts.length > 0 && (
              <p className="text-[13px] text-dim">
                {copy.ticket.parts}: {p.spare_parts.join('; ')}
              </p>
            )}
            <p className="text-[13px] text-dim">
              {copy.ticket.sources}:{' '}
              {p.references.map((r) => sourceLabel({ short: r.manual, pdf_page: r.pdf_page })).join(' · ')}
            </p>
          </div>
        </details>
      </div>
    </section>
  )
}
