import { Fragment, useMemo, useState } from 'react'
import { OUTCOMES_EXPORT, type FleetStatus, type FleetView, type VehicleBrief } from '../api'
import { copy } from '../copy'
import { rowBadges } from '../lib/checks'
import { outcomesPlace, reasonParts } from '../lib/fleet'
import { dateRu, plateKey } from '../lib/format'

export type Role = 'mechanic' | 'chief'

const statusTone = { normal: 'text-ok', attention: 'text-warn', quarantine: 'text-stop' } as const
const dot = { normal: 'bg-ok', attention: 'bg-warn', quarantine: 'bg-stop' } as const
const STATUSES: FleetStatus[] = ['quarantine', 'attention', 'normal']
// a badge drawn as a label: «заявка создана», «результат не подходит двигателю» (lib/checks.ts, rowBadges)
const BADGE_LABEL = 'inline-block rounded-md border border-line px-1.5 py-px leading-none whitespace-nowrap text-dim'

/** The label loop for the chief mechanic in one 48 px row: how often the inspection confirmed the acoustic
 *  check, out of how many tickets with an outcome, out of how many tickets. The row is the link to the file
 *  with every ticket and its outcome, for the owners of the model. Nothing is shown until there is a ticket. */
function OutcomesRow({ outcomes }: { outcomes: FleetView['outcomes'] }) {
  return (
    <a
      href={OUTCOMES_EXPORT}
      download="outcomes.csv"
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
        <path d="M10 3v9M6 8.5l4 4 4-4M4 16h12" />
      </svg>
      <span className="sr-only">{copy.chief.export}</span>
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
            {v.vehicle_id} <span className="text-[13px] font-normal text-mute">{v.garage_no}</span>
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
                reasonParts(v.fleet.reason).map((part, i) => (
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
            {withReason && <span>{v.fleet.reason}</span>}
            {drawn}
          </p>
        )}
      </div>
    </button>
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
  const outcomes = role === 'chief' && fleet !== null && fleet.outcomes.tickets > 0 && (
    <li className="py-2">
      <OutcomesRow outcomes={fleet.outcomes} />
    </li>
  )
  const outcomesAt = outcomes ? outcomesPlace(shown.length, plateKey(query) !== '' || only !== null) : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 8 px between the blocks, 12 px above them, 8 px below and a role switch without its inner
          padding: with 48 px controls and the legend the list would otherwise start lower than it did, and
          lose a row at 320×568. */}
      <div className="space-y-2 border-b border-line px-4 pt-3 pb-2">
        <p className="text-[13px] leading-none text-dim">{copy.product}</p>
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-[22px] leading-[1.15] font-semibold">{copy.fleet.title}</h1>
          <div
            className="flex rounded-lg border border-line text-[13px]"
            role="radiogroup"
            aria-label={copy.role.label}
          >
            {(['mechanic', 'chief'] as const).map((r) => (
              <button
                key={r}
                type="button"
                role="radio"
                aria-checked={role === r}
                onClick={() => onRole(r)}
                className="min-h-12 rounded-[7px] px-2.5 whitespace-nowrap text-dim aria-checked:bg-surface-2 aria-checked:text-text"
              >
                {copy.role[r]}
              </button>
            ))}
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
                // pressed: the card surface, not the input one, where «карантин» in red measured 4,44:1
                className="rounded-lg border border-line px-3 py-2 text-left aria-pressed:border-text aria-pressed:bg-surface"
              >
                <span className="block text-[22px] leading-[1.15] font-semibold">{fleet.counts[s]}</span>
                <span className={`flex items-center gap-1.5 text-[12px] ${statusTone[s]}`}>
                  <span className={`size-2 shrink-0 rounded-full ${dot[s]}`} aria-hidden />
                  {copy.fleetStatus[s]}
                </span>
              </button>
            ))}
          </div>
        )}
        {fleet && (
          <details className="text-[13px] text-dim">
            {/* a 48 px target in a 40 px line: it reaches 4 px into the gaps above and below */}
            <summary className="-my-1 flex min-h-12 cursor-pointer list-none items-center text-accent [&::-webkit-details-marker]:hidden">
              {copy.chief.legendTitle}
            </summary>
            <p className="pb-1">{copy.chief.legend}</p>
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
        {role === 'chief' && shown.length > 0 && (
          <p className="px-4 pt-1.5 pb-0.5 text-[13px] text-mute">{only ? copy.fleetStatus[only] : copy.chief.first}</p>
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
