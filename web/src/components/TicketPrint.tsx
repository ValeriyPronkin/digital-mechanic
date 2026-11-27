import type { TicketView, VehicleDetail } from '../api'
import { copy } from '../copy'
import { dateTimeRu } from '../lib/format'
import { sheetLines, verdictWord, type SheetLine } from '../lib/sheet'
import '../print.css'

const OUTCOMES = ['confirmed', 'not_confirmed', 'other_fault'] as const

/** A work or a part and, after a dash, where it is in the manual: «— ЯМЗ-236… Руководство по ремонту, стр. 269».
 *  A line found in the machine reading of a page image says so, as on the ticket sheet. */
function Line({ line }: { line: SheetLine }) {
  return (
    <li>
      {line.text}
      {line.page && (
        <span className="ps-page">
          {' '}
          — {line.page}
          {line.scanned && `, ${copy.thread.scanned}`}
        </span>
      )}
    </li>
  )
}

/** A sent ticket as a sheet of paper for the person who does the defect inspection: a work order, not a
 *  picture of the screen. What is read first is largest (the vehicle, the ticket's number, the priority);
 *  then what the check concluded, the works as a numbered list and the parts, each with its page of the
 *  manual when the ticket keeps it (lib/sheet.ts); at the foot, where the result is ticked and a note and a
 *  signature are written by hand. Drawn only in print (print.css): the ticket card puts it on the page for
 *  the time of a print. Ported from Nikita's interface (components/TicketPrint.tsx). */
export function TicketPrint({ ticket, vehicle }: { ticket: TicketView; vehicle: VehicleDetail | null }) {
  const p = ticket.payload
  const check = vehicle?.sessions.find((s) => s.session_id === p.session_id)
  // every work and part with its own page; or, for a ticket stored without them, the pages once under the works
  const { works, parts, pages } = sheetLines(p, ticket.lines)
  const [verdict, conclusion] = verdictWord(p.conclusion)
  const changed = ticket.urgency_proposed && ticket.urgency_proposed !== p.urgency
  return (
    <article className="print-sheet">
      <p className="ps-product">
        {copy.product} · {copy.ticket.title}
      </p>
      <div className="ps-head">
        <p className="ps-plate">
          {ticket.vehicle_id} {vehicle && <span>{vehicle.garage_no}</span>}
        </p>
        <p className="ps-number">{ticket.ticket_id}</p>
      </div>
      <p className="ps-priority">
        {copy.ticket.urgency}: {copy.urgency[p.urgency]}
        {changed && ticket.urgency_proposed && (
          <span>
            {' '}
            ({copy.ticket.proposed} {copy.urgency[ticket.urgency_proposed]})
          </span>
        )}
      </p>
      {vehicle && (
        <p className="ps-vehicle">
          {vehicle.model ?? vehicle.make} · {copy.vehicle.engine} {vehicle.engine_model}
        </p>
      )}
      <p className="ps-meta">
        {copy.print.ticketOf(dateTimeRu(ticket.created_at))} ·{' '}
        {copy.print.checkOf(p.session_id, check ? dateTimeRu(check.checked_at) : null)}
      </p>

      <section>
        <h2>{copy.ticket.conclusion}</h2>
        <p>
          {verdict && <b>{verdict}: </b>}
          {conclusion}
        </p>
      </section>

      <section>
        <h2>{copy.ticket.operations}</h2>
        <ol>
          {works.map((w, i) => (
            <Line key={i} line={w} />
          ))}
        </ol>
      </section>

      <section>
        <h2>{copy.ticket.parts}</h2>
        {parts.some((part) => part.page) ? (
          <ul>
            {parts.map((part, i) => (
              <Line key={i} line={part} />
            ))}
          </ul>
        ) : (
          <p>{parts.length > 0 ? parts.map((part) => part.text).join('; ') : copy.ticket.noParts}</p>
        )}
      </section>

      {pages.length > 0 && (
        <section>
          <h2>{copy.guide.pages}</h2>
          <p>{pages.join(' · ')}</p>
        </section>
      )}

      <div className="ps-result">
        <p>
          <b>{copy.print.result}</b>
        </p>
        <p className="ps-boxes">
          {OUTCOMES.map((o) => (
            <span key={o} className="ps-box" data-on={ticket.outcome === o}>
              {copy.print.outcome[o]}
            </span>
          ))}
        </p>
        {/* a note already recorded is printed; there is still a line to add to it by hand */}
        {ticket.outcome_note && (
          <p className="ps-noted">
            {copy.ticket.outcomeNote}: {ticket.outcome_note}
          </p>
        )}
        <p className="ps-rule">
          {!ticket.outcome_note && <span>{copy.ticket.outcomeNote}</span>}
          <i />
        </p>
        {!ticket.outcome_note && (
          <p className="ps-rule">
            <i />
          </p>
        )}
        <p className="ps-rule ps-sign">
          <span>{copy.print.date}</span>
          <i />
          <span>{copy.print.signature}</span>
          <i />
        </p>
      </div>
    </article>
  )
}
