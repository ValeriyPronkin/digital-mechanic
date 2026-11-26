import type { SessionBrief } from '../api'
import { copy } from '../copy'
import { checkLook, lineRuns } from '../lib/checks'
import { dateShortRu, num } from '../lib/format'

/** The anomaly score over the last checks (B2). One series, so no legend: the title names it.
 *  Each point is a button that selects that check; a failed recording has no value and sits on the axis.
 *  A check whose result does not fit the engine keeps its point, hollow, off the line (lib/checks, lineRuns).
 *  Lines are SVG; points and labels are HTML, so type stays the same size at any width. */
export function ScoreChart({
  sessions,
  selected,
  onSelect,
  trend,
}: {
  sessions: SessionBrief[]
  selected: string
  onSelect: (id: string) => void
  trend: string
}) {
  const n = sessions.length
  const x = (i: number) => (n === 1 ? 50 : 7 + (i * 86) / (n - 1))
  const valid = sessions.map((s, i) => ({ s, i })).filter((p) => p.s.anomaly_score !== null)
  const runs = lineRuns(sessions)

  return (
    <figure className="space-y-2">
      <figcaption className="text-[13px] text-dim">{copy.chart.title}</figcaption>

      {/* room above the plot for the value label of a point near 1 */}
      <div className="relative mt-7 h-28" role="group" aria-label={copy.chart.title}>
        {[1, 0.5, 0].map((level) => (
          <div key={level} className="absolute inset-x-0 h-px bg-line" style={{ bottom: `${level * 100}%` }} />
        ))}
        {(
          [
            [1, '1'],
            [0.5, copy.chart.threshold],
            [0, '0'],
          ] as const
        ).map(([level, label]) => (
          <span
            key={level}
            className="absolute left-0 -translate-y-px bg-bg pr-1 text-[11px] leading-none text-mute"
            style={{ bottom: `calc(${level * 100}% + 3px)` }}
          >
            {label}
          </span>
        ))}

        <svg
          className="absolute inset-0 size-full overflow-visible"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden
        >
          {runs
            .filter((run) => run.length > 1)
            .map((run, k) => (
              <polyline
                key={k}
                points={run.map(({ s, i }) => `${x(i)},${100 - s.anomaly_score! * 100}`).join(' ')}
                fill="none"
                stroke="var(--color-series)"
                strokeWidth="2"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            ))}
        </svg>

        {sessions.map((s, i) => {
          const failed = s.anomaly_score === null
          const isSelected = s.session_id === selected
          const label = `${dateShortRu(s.checked_at)} · ${checkLook(s).word}${failed ? '' : ` · ${num(s.anomaly_score!)}`}`
          return (
            <button
              key={s.session_id}
              type="button"
              onClick={() => onSelect(s.session_id)}
              aria-label={label}
              aria-pressed={isSelected}
              className="group absolute grid size-12 -translate-x-1/2 translate-y-1/2 place-items-center rounded-full"
              style={{ left: `${x(i)}%`, bottom: `${failed ? 0 : s.anomaly_score! * 100}%` }}
            >
              <span
                // hollow and grey: a check that is no reading of the engine (a recording that failed, a
                // result that does not fit the engine); the point stays where its score puts it
                className={`block rounded-full ring-2 ring-bg ${
                  failed || s.fits_engine === false ? 'size-2.5 border-2 border-mute bg-bg' : 'size-2.5 bg-series'
                } ${isSelected ? 'outline-2 outline-offset-2 outline-text' : ''}`}
              />
              <span
                // a label in words («не диагноз · 0,76», «проверка не удалась») is wider than the point's
                // 48 px: at the first and the last point it is pinned to the plot's edge, not centred past it
                className={`pointer-events-none absolute bottom-9 rounded-md bg-surface-2 px-1.5 py-0.5 text-[12px] whitespace-nowrap text-text ${
                  n > 1 && i === n - 1 ? 'right-1' : n > 1 && i === 0 ? 'left-1' : ''
                } ${isSelected ? '' : 'hidden group-hover:block group-focus-visible:block'}`}
              >
                {failed
                  ? copy.status.check_failed
                  : s.fits_engine === false
                    ? `${checkLook(s).word} · ${num(s.anomaly_score!)}`
                    : num(s.anomaly_score!)}
              </span>
            </button>
          )
        })}
      </div>

      <div className="relative h-4 text-[11px] text-mute" aria-hidden>
        {sessions.map((s, i) => (
          <span key={s.session_id} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${x(i)}%` }}>
            {dateShortRu(s.checked_at)}
          </span>
        ))}
      </div>

      <p className="text-[13px] text-dim">{trend}</p>

      <table className="sr-only">
        <caption>{copy.chart.title}</caption>
        <tbody>
          {valid.map(({ s }) => (
            <tr key={s.session_id}>
              <th scope="row">{dateShortRu(s.checked_at)}</th>
              <td>{checkLook(s).word}</td>
              <td>{num(s.anomaly_score!)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
