import { useEffect, useState } from 'react'
import { ApiError, exportUrl, getThreads, resumeThread, type ThreadRow } from '../api'
import { copy } from '../copy'
import { firstRows, FIRST_ROWS, historyRows } from '../lib/history'

/** «Обращения по машине» (#92, B1 — память по машине): earlier conversations about this vehicle, newest first.
 *  «Продолжить» makes one the current conversation on this phone (the next question goes to it);
 *  «Для рекламации» opens the record for printing: every answer with its pages, the model, and whether the
 *  chain of records is whole. Folded by default: the vehicle screen starts with the check, not the archive.
 *  Asked again whenever `refresh` changes (an answer ended, a conversation was continued). */
export function ThreadHistory({
  vehicleId,
  currentId,
  refresh,
  disabled,
  onResumed,
}: {
  vehicleId: string
  currentId: string | null
  refresh: number
  disabled: boolean // an answer is being written: continuing another conversation would cut it
  onResumed: () => void
}) {
  const [rows, setRows] = useState<ThreadRow[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState<string | null>(null) // the conversation being opened
  const [problem, setProblem] = useState<string | null>(null)
  const [all, setAll] = useState(false) // «Показать все»: the newest three until then

  useEffect(() => {
    let stale = false
    getThreads(vehicleId)
      .then((list) => {
        if (stale) return
        setRows(list)
        setFailed(false)
      })
      .catch(() => !stale && setFailed(true))
    return () => {
      stale = true
    }
  }, [vehicleId, refresh])

  const resume = async (threadId: string) => {
    setBusy(threadId)
    setProblem(null)
    try {
      await resumeThread(threadId, vehicleId)
      onResumed()
    } catch (e) {
      // 404 «срок хранения истёк» — the server's own words; anything else — ours
      setProblem(e instanceof ApiError && e.status === 404 && e.detail ? e.detail : copy.history.resumeFailed)
    } finally {
      setBusy(null)
    }
  }

  if (failed) return <p className="text-[13px] text-dim">{copy.history.loadFailed}</p>
  if (!rows || rows.length === 0) return null
  const shown = historyRows(rows, currentId)
  const listed = all ? shown : firstRows(shown)

  return (
    <details className="group rounded-xl border border-line bg-surface" data-history>
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-2 px-4 [&::-webkit-details-marker]:hidden">
        <span className="text-[13px] text-dim">
          {copy.history.title} · {copy.history.count(shown.length)}
        </span>
        <span aria-hidden className="text-dim transition-transform group-open:rotate-180">
          ▾
        </span>
      </summary>
      <ul className="divide-y divide-line border-t border-line">
        {listed.map((r) => (
          <li key={r.id} className="space-y-2 px-4 py-3">
            <p className="text-[13px] text-dim">
              {r.when} · {r.status}
              {r.ticket && <> · {r.ticket}</>} · {r.records}
            </p>
            <p className="line-clamp-2">{r.topic}</p>
            <div className="flex flex-wrap gap-2">
              {r.current ? (
                <span className="inline-flex min-h-12 items-center px-1 text-[13px] text-accent">
                  {copy.history.current}
                </span>
              ) : (
                <button
                  type="button"
                  disabled={disabled || busy !== null}
                  onClick={() => void resume(r.id)}
                  className="min-h-12 rounded-lg border border-line px-4 enabled:hover:bg-surface-2 disabled:opacity-50"
                >
                  {busy === r.id ? copy.history.resuming : copy.history.resume}
                </button>
              )}
              {r.canClaim && (
                <>
                  <a
                    href={exportUrl(vehicleId, r.id, 'html')}
                    target="_blank"
                    rel="noopener"
                    title={copy.history.claimHint}
                    className="inline-flex min-h-12 items-center rounded-lg border border-line px-4 hover:bg-surface-2"
                  >
                    {copy.history.claim}
                  </a>
                  <a
                    href={exportUrl(vehicleId, r.id, 'json')}
                    target="_blank"
                    rel="noopener"
                    className="inline-flex min-h-12 items-center px-2 text-[13px] text-dim hover:text-text"
                  >
                    {copy.history.json}
                  </a>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      {shown.length > FIRST_ROWS && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll(!all)}
          className="flex min-h-12 w-full items-center border-t border-line px-4 text-[13px] text-accent hover:bg-surface-2"
        >
          {all ? copy.history.showFewer : copy.history.showAll(shown.length)}
        </button>
      )}
      {problem && (
        <p role="alert" className="border-t border-line px-4 py-3 text-[13px] text-warn">
          {problem}
        </p>
      )}
    </details>
  )
}
