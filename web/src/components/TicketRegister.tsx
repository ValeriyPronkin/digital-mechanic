import { Fragment, useCallback, useEffect, useState } from 'react'
import { getAllTickets, OUTCOMES_EXPORT, type TicketRow } from '../api'
import { copy } from '../copy'
import { reasonParts } from '../lib/fleet'
import { dateRu, dateShortRu } from '../lib/format'
import {
  byFault,
  priorityChanged,
  shownTickets,
  ticketState,
  totals,
  type RegisterFilter,
  type TicketState,
} from '../lib/register'

/** The address of the register: `#/tickets`, in the pane where a vehicle opens. */
export const REGISTER = 'tickets'

const FILTERS: RegisterFilter[] = ['all', 'waiting', 'recorded']
const MARKS: Record<TicketState, string> = {
  waiting: 'M6 1.75a4.25 4.25 0 1 0 0 8.5a4.25 4.25 0 1 0 0-8.5', // a ring: nothing yet
  confirmed: 'M2 6.5l2.75 2.75L10 3.5',
  not_confirmed: 'M2.75 2.75l6.5 6.5M9.25 2.75l-6.5 6.5',
  other_fault: 'M2 4.25h8M2 7.75h8M7.75 1.75l-3.5 8.5', // «≠»: a fault, but not the one the check named
}

/** What came of a ticket, as a mark and the words. No colour: «не подтвердилось» is good news for the engine
 *  and bad news for the acoustic check, so neither green nor red would be true for both readers. */
function State({ state }: { state: TicketState }) {
  return (
    <span className={`inline-flex items-baseline gap-1.5 ${state === 'waiting' ? 'text-dim' : ''}`}>
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 translate-y-px"
        aria-hidden
      >
        <path d={MARKS[state]} />
      </svg>
      <span className="whitespace-nowrap">{copy.register.state[state]}</span>
    </span>
  )
}

/** «средний (предложен высокий)» when the mechanic sent the ticket with another priority: the card's words. */
const priorityWords = (t: TicketRow) =>
  copy.urgency[t.payload.urgency] +
  (priorityChanged(t) && t.urgency_proposed ? ` (${copy.ticket.proposed} ${copy.urgency[t.urgency_proposed]})` : '')

/** A line that breaks only between its facts, as the reason line of a fleet row does (lib/fleet.ts). */
function Facts({ line }: { line: string }) {
  return reasonParts(line).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && ' '}
      <span className={i > 0 ? 'whitespace-nowrap' : undefined}>{part}</span>
    </Fragment>
  ))
}

// the vehicle's screen, where the ticket's card is with its outcome, its pages and «Распечатать»
const vehicleHref = (t: TicketRow) => `#/${encodeURIComponent(t.vehicle_id)}`

/** A ticket on a phone, as a line of a foreman's journal: which ticket of which vehicle and when; what the
 *  check named and how urgent it was sent; what came of it, with the start of the note. */
function Row({ t }: { t: TicketRow }) {
  return (
    <a href={vehicleHref(t)} className="block px-4 py-2.5 hover:bg-surface">
      <p className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate">
          <span className="font-semibold">{t.ticket_id}</span> {t.vehicle_id}{' '}
          <span className="text-[13px] text-mute">{t.garage_no}</span>
        </span>
        <span className="shrink-0 text-[13px] text-mute">{dateShortRu(t.created_at)}</span>
      </p>
      <p className="mt-0.5 text-[13px] text-dim">
        <Facts line={`${t.fault_title} · ${copy.ticket.urgency.toLowerCase()}: ${priorityWords(t)}`} />
      </p>
      <p className="mt-0.5 flex items-baseline gap-1.5 text-[13px]">
        <State state={ticketState(t)} />
        {t.outcome_note && <span className="min-w-0 truncate text-dim">— {t.outcome_note}</span>}
      </p>
    </a>
  )
}

/** The same tickets as a table, when the pane is 900 px or wider. The note stands under the state it
 *  explains, as it follows it on a phone. */
function Table({ rows }: { rows: TicketRow[] }) {
  const c = copy.register.columns
  const head = 'py-2 pr-4 font-normal first:pl-4'
  const cell = 'py-3 pr-4 first:pl-4'
  return (
    <table className="w-full table-fixed text-left">
      <colgroup>
        <col className="w-[104px]" />
        <col className="w-[140px]" />
        <col className="w-[96px]" />
        <col className="w-[22%]" />
        <col className="w-[168px]" />
        <col />
      </colgroup>
      <thead>
        <tr className="border-b border-line text-[13px] text-dim">
          {[c.ticket, c.vehicle, c.date, c.fault, c.priority, c.state].map((name) => (
            <th key={name} scope="col" className={head}>
              {name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map((t) => (
          <tr
            key={t.id}
            // the number is the link, for the keyboard; a click anywhere in the row goes the same way
            onClick={() => {
              window.location.hash = vehicleHref(t)
            }}
            className="h-12 cursor-pointer align-baseline hover:bg-surface"
          >
            <td className={`${cell} whitespace-nowrap`}>
              <a href={vehicleHref(t)} className="font-semibold">
                {t.ticket_id}
              </a>
            </td>
            <td className={`${cell} whitespace-nowrap`}>
              {t.vehicle_id} <span className="text-[13px] text-mute">{t.garage_no}</span>
            </td>
            <td className={`${cell} text-[13px] whitespace-nowrap text-dim`}>{dateRu(t.created_at)}</td>
            <td className={`${cell} text-[13px]`}>{t.fault_title}</td>
            <td className={`${cell} text-[13px]`}>
              {copy.urgency[t.payload.urgency]}
              {priorityChanged(t) && t.urgency_proposed && (
                <span className="block whitespace-nowrap text-dim">
                  ({copy.ticket.proposed} {copy.urgency[t.urgency_proposed]})
                </span>
              )}
            </td>
            <td className={`${cell} text-[13px]`}>
              <State state={ticketState(t)} />
              {t.outcome_note && (
                <span className="block truncate text-dim" title={t.outcome_note}>
                  {t.outcome_note}
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** The chief mechanic's register: every ticket of the fleet, the priority it was sent with, what the defect
 *  inspection found, and how often the acoustic check was right, in all and by fault type. A phone gets
 *  rows; a pane of 900 px or more gets a table of the same facts. The counts are about every ticket,
 *  whatever the filter shows. Ported from Nikita's interface (components/TicketRegister.tsx). */
export function TicketRegister({ onBack }: { onBack: () => void }) {
  const [tickets, setTickets] = useState<TicketRow[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [show, setShow] = useState<RegisterFilter>('all')
  const fetchTickets = useCallback(() => {
    getAllTickets()
      .then(setTickets)
      .catch(() => setFailed(true))
  }, [])
  useEffect(fetchTickets, [fetchTickets])
  const retry = () => {
    setFailed(false) // back to «Загружаем заявки…» while the request runs
    fetchTickets()
  }

  const sum = totals(tickets ?? [])
  const rows = shownTickets(tickets ?? [], show)
  const faults = byFault(tickets ?? [])
  const count = { all: sum.tickets, waiting: sum.waiting, recorded: sum.recorded }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-line">
        <div className="flex min-h-14 items-center gap-1 px-4">
          <button
            type="button"
            onClick={onBack}
            aria-label={copy.vehicle.back}
            className="-ml-3 grid size-12 shrink-0 place-items-center text-dim hover:text-text min-[900px]:hidden"
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
              <path d="M12 4l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <h1 className="min-w-0 flex-1 truncate text-[17px] font-semibold">{copy.register.title}</h1>
        </div>
      </header>
      <div className="@container min-h-0 flex-1 overflow-y-auto">
        {tickets === null && !failed && (
          <p className="p-4 text-dim" role="status">
            {copy.register.loading}
          </p>
        )}
        {tickets === null && failed && (
          <div className="space-y-3 p-4" role="alert">
            <p>{copy.register.loadFailed}</p>
            <button type="button" onClick={retry} className="min-h-12 rounded-lg border border-line px-4">
              {copy.retry}
            </button>
          </div>
        )}
        {tickets !== null && tickets.length === 0 && <p className="p-4 text-dim">{copy.register.empty}</p>}
        {tickets !== null && tickets.length > 0 && (
          <>
            <div className="space-y-2 px-4 pt-3 pb-2">
              <p>{sum.recorded > 0 ? copy.chief.outcomes(sum.confirmed, sum.recorded) : copy.chief.outcomesNone}</p>
              <div
                className="grid grid-cols-3 gap-2 @min-[900px]:max-w-md"
                role="radiogroup"
                aria-label={copy.register.show}
              >
                {FILTERS.map((f) => (
                  <button
                    key={f}
                    type="button"
                    role="radio"
                    aria-checked={show === f}
                    onClick={() => setShow(f)}
                    className="flex min-h-12 flex-col items-start rounded-lg border border-line px-3 py-1.5 text-left aria-checked:border-accent aria-checked:bg-surface-2"
                  >
                    <span className="text-[17px] leading-tight font-semibold">{count[f]}</span>
                    <span className="text-[13px] leading-tight text-dim">{copy.register.filter[f]}</span>
                  </button>
                ))}
              </div>
            </div>

            {rows.length === 0 && show !== 'all' && (
              <p className="border-t border-line p-4 text-dim">{copy.register.emptyFilter[show]}</p>
            )}
            {rows.length > 0 && (
              <>
                <ul className="divide-y divide-line border-y border-line @min-[900px]:hidden">
                  {rows.map((t) => (
                    <li key={t.id}>
                      <Row t={t} />
                    </li>
                  ))}
                </ul>
                <div className="hidden border-y border-line @min-[900px]:block">
                  <Table rows={rows} />
                </div>
              </>
            )}

            <div className="space-y-4 px-4 pt-4 pb-6">
              {faults.length > 0 && (
                <section className="space-y-1">
                  <h2 className="text-[13px] text-dim">{copy.register.byFault}</h2>
                  <ul className="space-y-1">
                    {faults.map((f) => (
                      // one sentence that wraps as text, between its facts only; «·» stays with the fact before it
                      <li key={f.code}>
                        {copy.register.faultLine(f.title, f.confirmed, f.recorded)}
                        {[
                          ...(f.otherFault > 0 ? [copy.register.faultOther(f.otherFault)] : []),
                          copy.register.faultTickets(f.tickets),
                        ].map((fact) => (
                          <Fragment key={fact}>
                            <span className="text-dim">{' '}·</span>{' '}
                            <span className="text-[13px] whitespace-nowrap text-dim">{fact}</span>
                          </Fragment>
                        ))}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <a
                href={OUTCOMES_EXPORT}
                download="outcomes.csv"
                className="flex min-h-12 items-center justify-between gap-3 rounded-lg border border-line px-3 py-1.5 text-[13px] leading-[1.25] hover:bg-surface @min-[900px]:max-w-md"
              >
                <span className="min-w-0">
                  <span className="block">{copy.register.export}</span>
                  <span className="block text-dim">{copy.register.exportHint}</span>
                </span>
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 text-accent"
                  aria-hidden
                >
                  <path d="M10 3v9M6 8.5l4 4 4-4M4 16h12" />
                </svg>
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
