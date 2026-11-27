import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import {
  getContradictions,
  type ContradictionStatus,
  type FleetStatus,
  type FleetView,
  type VehicleBrief,
} from '../api'
import { copy } from '../copy'
import { rowBadges } from '../lib/checks'
import { queueCounts, queueTotal } from '../lib/contradictions'
import { outcomesPlace, reasonLine, reasonParts } from '../lib/fleet'
import { dateRu, plateKey } from '../lib/format'
import { CHECKED, nextChoice, PRESSED_STATUS } from '../lib/ui'
import { QueueRow } from './ContradictionQueue'
import { REGISTER } from './TicketRegister'
import { ThemeSelect } from './ThemeSelect'

export type Role = 'mechanic' | 'chief'

const statusTone = { normal: 'text-ok', attention: 'text-warn', quarantine: 'text-stop' } as const
const dot = { normal: 'bg-ok', attention: 'bg-warn', quarantine: 'bg-stop' } as const
const STATUSES: FleetStatus[] = ['quarantine', 'attention', 'normal']
const ROLES: Role[] = ['mechanic', 'chief']
// a badge drawn as a label: «заявка создана», «результат не подходит двигателю» (lib/checks.ts, rowBadges)
const BADGE_LABEL = 'inline-block rounded-md border border-line px-1.5 py-px leading-none whitespace-nowrap text-dim'

/** The label loop for the chief mechanic in one 48 px row: how often the inspection confirmed the acoustic
 *  check, out of how many tickets with an outcome, out of how many tickets. The row opens the register of
 *  tickets (TicketRegister), where each ticket is with its result and the file for the owners of the model.
 *  Nothing is shown until there is a ticket. */
function OutcomesRow({ outcomes }: { outcomes: FleetView['outcomes'] }) {
  return (
    <a
      href={`#/${REGISTER}`}
      // `relative` keeps the screen reader's «Скачать выгрузку» inside the list: positioned against the page it
      // made the page itself scroll
      className="relative mx-4 flex min-h-12 items-center justify-between gap-3 rounded-lg border border-line px-3 py-1 text-[13px] leading-[1.25] hover:bg-surface"
    >
      <span className="min-w-0">
        <span className="block">
          {outcomes.recorded > 0 ? copy.chief.outcomes(outcomes.confirmed, outcomes.recorded) : copy.chief.outcomesNone}
        </span>
        <span className="block text-dim">{copy.chief.outcomesOf(outcomes.tickets, outcomes.recorded)}</span>
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
        <path d="M8 4l6 6-6 6" />
      </svg>
      <span className="sr-only">{copy.chief.openRegister}</span>
    </a>
  )
}

function Row({
  v,
  role,
  selected,
  onSelect,
}: {
  v: VehicleBrief
  role: Role
  selected: boolean
  onSelect: () => void
}) {
  // Labels are shown next to whatever else the row says; the other badges replace a line of it.
  const { labels, instead, withReason } = rowBadges(v.fleet.badges)
  const drawn = labels.map((label) => (
    <span key={label} className={BADGE_LABEL}>
      {label}
    </span>
  ))
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected}
      // selected (wide screen): the card surface; on the input surface the red status word is 4,44:1
      className="flex min-h-16 w-full items-center px-4 py-2.5 text-left hover:bg-surface aria-[current=true]:bg-surface"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <p className="truncate font-semibold">
            {v.vehicle_id}{' '}
            <span className="text-[13px] font-normal text-mute">
              {v.garage_no}
              {/* the chief's row has no line for the model: it goes with the garage number */}
              {role === 'chief' && ` · ${v.model ?? v.make}`}
            </span>
          </p>
          {v.fleet.status ? (
            <p className={`flex shrink-0 items-center gap-1.5 text-[13px] font-semibold ${statusTone[v.fleet.status]}`}>
              <span className={`size-2 rounded-full ${dot[v.fleet.status]}`} aria-hidden />
              {v.fleet.label}
            </p>
          ) : (
            <p className="shrink-0 text-[13px] text-dim">{copy.fleet.noValidCheck}</p>
          )}
        </div>
        {role === 'chief' ? (
          // Whether the reason fits one line depends on the phone and its font, so the row does not count
          // pixels (it used to have 15 px sides so that one string fitted 390 px exactly). The line breaks only
          // between its facts (lib/fleet.ts), and it may run 8 px into the row's right padding: «Клапанный
          // механизм · оценка 0,93 · приоритет высокий», 360 px wide, has 366 px at 390 px.
          <p className="mt-0.5 -mr-2 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-[13px] text-dim">
            <span>
              {instead ??
                reasonParts(reasonLine(v.fleet)).map((part, i) => (
                  <Fragment key={i}>
                    {i > 0 && ' '}
                    <span className={i > 0 ? 'whitespace-nowrap' : undefined}>{part}</span>
                  </Fragment>
                ))}
            </span>
            {drawn}
          </p>
        ) : (
          <div className="mt-0.5 flex flex-wrap items-baseline justify-between gap-x-3 text-[13px]">
            <p className="text-dim">
              {v.model ?? v.make} · {v.engine_model}
            </p>
            <p className="shrink-0 text-mute">
              {instead ?? (v.last_session ? `${copy.fleet.check} ${dateRu(v.last_session.checked_at)}` : '')}
            </p>
          </div>
        )}
        {labels.length > 0 && role !== 'chief' && (
          <p className="mt-1 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-[13px] text-dim">
            {withReason && <span>{reasonLine(v.fleet)}</span>}
            {drawn}
          </p>
        )}
      </div>
    </button>
  )
}

/** Mechanic or chief mechanic: one segmented control. The track is the container, the chosen segment is
 *  inset in it, both segments are 32 px high and the track 38 px, so the control is no heavier than the
 *  title beside it; each segment still takes a tap 48 px high (a layer 8 px above and below it). One tab
 *  stop: the arrow keys move the choice, as in a group of radio buttons. */
function RoleSwitch({ role, onRole }: { role: Role; onRole: (role: Role) => void }) {
  const segments = useRef<(HTMLButtonElement | null)[]>([])
  return (
    <div
      className="flex rounded-lg border border-line p-0.5 text-[13px]"
      role="radiogroup"
      aria-label={copy.role.label}
      onKeyDown={(e) => {
        const to = nextChoice(ROLES.indexOf(role), e.key, ROLES.length)
        if (to === null) return
        e.preventDefault()
        onRole(ROLES[to])
        segments.current[to]?.focus()
      }}
    >
      {ROLES.map((r, i) => (
        <button
          key={r}
          ref={(el) => {
            segments.current[i] = el
          }}
          type="button"
          role="radio"
          aria-checked={role === r}
          tabIndex={role === r ? 0 : -1}
          onClick={() => onRole(r)}
          className={`relative h-8 rounded-md border border-transparent px-2.5 whitespace-nowrap text-dim hover:text-text before:absolute before:inset-x-0 before:-inset-y-2 before:content-[''] ${CHECKED}`}
        >
          {copy.role[r]}
        </button>
      ))}
    </div>
  )
}

/** The fleet. Mechanic: find a vehicle by plate or garage number. Chief mechanic (B3): counts by status
 *  that filter the list, and the list in the order to deal with the vehicles. */
export function FleetList({
  fleet,
  failed,
  onRetry,
  role,
  onRole,
  selected,
  onSelect,
}: {
  fleet: FleetView | null // null: not loaded yet, or the load failed
  failed: boolean
  onRetry: () => void
  role: Role
  onRole: (role: Role) => void
  selected: string | null
  onSelect: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [only, setOnly] = useState<FleetStatus | null>(null)

  const shown = useMemo(() => {
    if (!fleet) return []
    const key = plateKey(query)
    let list = fleet.vehicles.filter(
      (v) => !key || plateKey(v.vehicle_id).includes(key) || plateKey(v.garage_no).includes(key),
    )
    if (role === 'chief') list = only ? list.filter((v) => v.fleet.status === only) : list
    else list = [...list].sort((a, b) => a.garage_no.localeCompare(b.garage_no, 'ru', { numeric: true }))
    return list
  }, [fleet, query, role, only])

  // The outcomes row is an item of the list, and `outcomesPlace` says which: after the third vehicle of the
  // full list, after the last match of a search or a status filter, nowhere when nothing matches. Its place
  // does not hang on the height of the view, so it does not move when the keyboard opens. It used to sit
  // above the list on a tall view and after it on a short one, by a media query on the height.
  // The queue of contradictions between manuals (#93) sits in the same place, under the outcomes row.
  const [queue, setQueue] = useState<Record<ContradictionStatus, number> | null>(null)
  useEffect(() => {
    if (role !== 'chief') return
    let live = true
    getContradictions('all')
      .then((items) => live && setQueue(queueCounts(items)))
      .catch(() => undefined) // no queue row; the fleet works without it
    return () => {
      live = false
    }
  }, [role, fleet])
  const hasTickets = role === 'chief' && fleet !== null && fleet.outcomes.tickets > 0
  const hasQueue = role === 'chief' && queue !== null && queueTotal(queue) > 0
  const outcomes = (hasTickets || hasQueue) && (
    <li className="space-y-2 py-2">
      {hasTickets && <OutcomesRow outcomes={fleet.outcomes} />}
      {hasQueue && <QueueRow counts={queue} />}
    </li>
  )
  const outcomesAt = outcomes ? outcomesPlace(shown.length, plateKey(query) !== '' || only !== null) : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* One left edge and one step: 12 px above the header, between its blocks and below it; the product
          line and the title are a pair, 8 px apart. The header is 16 px shorter than it was with 8 px steps
          and 48 px tall controls drawn at full height, so the list still shows its first three rows at
          320×568. */}
      <div className="space-y-3 border-b border-line px-4 py-3">
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[13px] leading-none text-dim">{copy.product}</p>
            <ThemeSelect />
          </div>
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-[22px] leading-[1.15] font-semibold">{copy.fleet.title}</h1>
            <RoleSwitch role={role} onRole={onRole} />
          </div>
        </div>

        {role === 'chief' && fleet && (
          <div className="grid grid-cols-3 gap-2">
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={only === s}
                onClick={() => setOnly(only === s ? null : s)}
                // The content starts at the top, so the three numbers stand on one line and the three labels
                // start on one line whichever of them wraps; a button would centre it, and the two short
                // cards used to hang lower than the long one.
                className={`flex flex-col items-start rounded-lg border border-line px-3 py-2 text-left hover:bg-surface ${PRESSED_STATUS}`}
              >
                <span className="text-[22px] leading-[1.15] font-semibold">{fleet.counts[s]}</span>
                {/* two lines are kept for the label («требует внимания» wraps in a narrow card), so the cards
                    are one height at every width; the dot belongs to the first line */}
                <span className={`flex min-h-[30px] items-start gap-1.5 text-[12px] leading-[15px] ${statusTone[s]}`}>
                  <span className={`mt-[3.5px] size-2 shrink-0 rounded-full ${dot[s]}`} aria-hidden />
                  {copy.fleetStatus[s]}
                </span>
              </button>
            ))}
          </div>
        )}
        {fleet && (
          <details className="text-[13px] text-dim">
            {/* a 44 px target in a 20 px line: it reaches up to the block above and down to the one below,
                and into neither */}
            <summary className="-my-3 flex min-h-11 cursor-pointer list-none items-center text-accent [&::-webkit-details-marker]:hidden">
              {copy.chief.legendTitle}
            </summary>
            <p className="pt-3">{copy.chief.legend}</p>
          </details>
        )}

        <input
          type="search"
          inputMode="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={copy.fleet.search}
          aria-label={copy.fleet.search}
          className="min-h-12 w-full rounded-lg border border-line bg-surface-2 px-3 placeholder:text-mute"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {fleet === null && !failed && (
          <p className="p-4 text-dim" role="status">
            {copy.fleet.loading}
          </p>
        )}
        {fleet === null && failed && (
          <div className="space-y-3 p-4" role="alert">
            <p>{copy.fleet.loadFailed}</p>
            <button type="button" onClick={onRetry} className="min-h-12 rounded-lg border border-line px-4">
              {copy.retry}
            </button>
          </div>
        )}
        {fleet !== null && shown.length === 0 && <p className="p-4 text-dim">{copy.fleet.empty}</p>}
        {role === 'chief' && shown.length > 0 && !only && (
          <p className="px-4 pt-1.5 pb-0.5 text-[13px] text-mute">{copy.chief.first}</p>
        )}
        {/* A pressed counter filters the list: the line above it says so and takes the filter off. The
            line is 32 px and «Сбросить» takes a tap 44 px high, up into the header's own 12 px. */}
        {role === 'chief' && only && (
          <p className="flex min-h-8 items-center justify-between gap-3 px-4 text-[13px] text-mute">
            <span>
              {copy.chief.shown}: {copy.fleetStatus[only]}
            </span>
            <button
              type="button"
              onClick={() => setOnly(null)}
              className="relative shrink-0 text-accent before:absolute before:-inset-x-3 before:-top-3 before:bottom-0 before:content-['']"
            >
              {copy.chief.reset}
            </button>
          </p>
        )}
        <ul className="divide-y divide-line">
          {shown.map((v, i) => (
            <Fragment key={v.vehicle_id}>
              {i === outcomesAt && outcomes}
              <li>
                <Row v={v} role={role} selected={selected === v.vehicle_id} onSelect={() => onSelect(v.vehicle_id)} />
              </li>
            </Fragment>
          ))}
          {outcomesAt === shown.length && outcomes}
        </ul>
      </div>
    </div>
  )
}
