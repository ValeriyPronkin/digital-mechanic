import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useVoice, voiceSupported } from '../useVoice'
import {
  ApiError,
  getTickets,
  getVehicle,
  type Block,
  type GuideBlock,
  type SessionBrief,
  type SourceItem,
  type TicketView,
  type VehicleDetail,
  type ContradictionBlock,
  type VerdictBlock,
} from '../api'
import { copy } from '../copy'
import { checkLook } from '../lib/checks'
import { dateShortRu, dateTimeRu } from '../lib/format'
import { mergeTickets, withTicket } from '../lib/tickets'
import { CHECKED, scrollsFurther } from '../lib/ui'
import { useThread, type AssistantTurn, type Turn } from '../useThread'
import { ActionLog } from './ActionLog'
import { Answer } from './Answer'
import { ContradictionCard } from './ContradictionCard'
import { GuideCard } from './GuideCard'
import { PageSheet } from './PageSheet'
import { SpeakButton } from './SpeakButton'
import { LEVEL_EVENT, REDO, getLevel, otherLevel, redoLevel, setLevel, type Level } from '../lib/level'
import { anchoringWhile } from '../lib/scroll'
import { ScoreChart } from './ScoreChart'
import { TicketCard } from './TicketCard'
import { TicketSheet } from './TicketSheet'
import { VerdictCard } from './VerdictCard'

function SessionPicker({
  sessions,
  selected,
  onSelect,
}: {
  sessions: SessionBrief[]
  selected: string
  onSelect: (id: string) => void
}) {
  return (
    <div
      // on a wide screen the checks wrap: a mouse wheel cannot scroll a row sideways
      className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 min-[900px]:flex-wrap"
      role="radiogroup"
      aria-label={copy.vehicle.checks}
    >
      {[...sessions].reverse().map((s) => {
        const look = checkLook(s) // a check that does not fit the engine: «не диагноз», a neutral dot
        return (
          <button
            key={s.session_id}
            type="button"
            role="radio"
            aria-checked={selected === s.session_id}
            onClick={() => onSelect(s.session_id)}
            className={`flex min-h-12 shrink-0 items-center gap-2 rounded-lg border border-line px-3 text-[13px] text-dim hover:text-text ${CHECKED}`}
          >
            <span className={`size-2 rounded-full ${look.dot}`} aria-hidden />
            <span>
              {dateShortRu(s.checked_at)} · {look.word}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function AssistantBlock({
  turn,
  sources,
  onOpenSource,
  manualNames,
  onRedo,
}: {
  onRedo?: (level: Level) => void // the last answer only: «Подробнее / Короче» for this answer
  turn: AssistantTurn
  sources: Record<string, SourceItem>
  onOpenSource: (s: SourceItem, quote?: string, scanned?: boolean) => void
  manualNames: Record<string, string>
}) {
  const notes: Record<string, string> = {
    round_limit: copy.thread.roundLimit,
    max_tokens: copy.thread.truncated,
    max_tokens_step: copy.thread.stepCut,
  }
  const note = turn.reason && Object.hasOwn(notes, turn.reason) ? notes[turn.reason] : null
  // The model was unavailable or refused: there is no answer to carry the pages, so the guide lists
  // them itself, under the line that says the explanation is missing.
  const noModel = turn.reason === 'model_unavailable' || turn.reason === 'refusal'
  const isGuide = (block: Block) => block.kind === 'guide'
  const show = (block: Block, key: number) =>
    block.kind === 'verdict' ? (
      <VerdictCard key={key} verdict={block as VerdictBlock} />
    ) : block.kind === 'guide' ? (
      <GuideCard
        key={key}
        guide={block as GuideBlock}
        sources={sources}
        onOpen={(s) => onOpenSource(s)}
        listPages={noModel}
      />
    ) : block.kind === 'error' ? (
      <p key={key} className="rounded-xl border border-line bg-surface px-4 py-3 text-warn">
        {String((block as { message: string }).message)}
      </p>
    ) : null
  return (
    <div className="space-y-3">
      {turn.blocks.map((block, i) => (noModel && isGuide(block) ? null : show(block, i)))}
      {turn.text && (
        <Answer
          text={turn.text}
          sources={sources}
          verified={new Set(turn.verification?.verified)}
          scanned={new Set(turn.verification?.scanned)}
          verification={turn.verification}
          onOpen={onOpenSource}
        />
      )}
      {/* the short spoken version: value, document, page — for busy hands (#14) */}
      {(() => {
        const answered = turn.passport?.question?.level
        if (!onRedo || turn.live || !turn.text || (answered !== 'expert' && answered !== 'steps')) return null
        const next = otherLevel(answered)
        return (
          <button
            type="button"
            onClick={() => onRedo(next)}
            className="min-h-12 rounded-lg border border-accent px-3 text-[13px] font-semibold text-accent"
          >
            {REDO[next].label}
          </button>
        )
      })()}
      {!turn.live && turn.speech && <SpeakButton speech={turn.speech} />}
      {/* manuals disagree: under the direct answer, as the code put it there (D-20) */}
      {turn.blocks
        .filter((b) => b.kind === 'contradiction')
        .map((b, i) => (
          <ContradictionCard
            key={`c${i}`}
            block={b as ContradictionBlock}
            sources={sources}
            onOpen={(s, quote) => onOpenSource(s, quote)}
          />
        ))}
      {turn.progress && (
        <p className="text-dim" role="status" aria-live="polite">
          {turn.progress}
        </p>
      )}
      {turn.error && <p className="text-warn">{turn.error}</p>}
      {noModel && turn.blocks.map((block, i) => (isGuide(block) ? show(block, i) : null))}
      {note && <p className="text-[13px] text-mute">{note}</p>}
      {!turn.live && (
        <ActionLog
          tools={turn.tools}
          usage={turn.usage}
          manualNames={manualNames}
          sources={sources}
          onOpen={(s) => onOpenSource(s)}
          passport={turn.passport}
        />
      )}
    </div>
  )
}

/** The slim bar of the screen. It is there from the first frame, so the way back to the fleet never
 *  depends on a request. */
function Header({ title, onBack, children }: { title: ReactNode; onBack: () => void; children?: ReactNode }) {
  return (
    // the 16 px at the sides belong to the centred column, as they do in the thread under the bar: on a
    // wide screen the title starts on the thread's left edge, not 16 px before it
    <header className="border-b border-line">
      <div className="mx-auto flex min-h-14 max-w-3xl items-center gap-1 px-4">
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
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-semibold">{title}</h1>
        {children}
      </div>
    </header>
  )
}

/** One vehicle: its checks, the result of the selected one, the conversation, the ticket. */
export function VehicleScreen({
  vehicleId,
  onBack,
  onTicketsChanged,
}: {
  vehicleId: string
  onBack: () => void
  onTicketsChanged?: () => void // a ticket was made or its outcome recorded: the fleet list shows both
}) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [problem, setProblem] = useState<'failed' | 'missing' | null>(null) // the vehicle did not load
  const [attempt, setAttempt] = useState(0)
  const [source, setSource] = useState<SourceItem | null>(null) // the manual page that is open
  const [quote, setQuote] = useState<string | undefined>() // the line the server found the number on
  const [scanned, setScanned] = useState<boolean | undefined>() // …and whether it was read from the page image
  const openSource = (s: SourceItem, q?: string, fromScan?: boolean) => {
    setSource(s)
    setQuote(q)
    setScanned(fromScan)
  }
  const [dismissed, setDismissed] = useState<string | null>(null) // a ticket draft the mechanic closed
  const [draft, setDraft] = useState('')
  const voice = useVoice((said) => setDraft(said.charAt(0).toUpperCase() + said.slice(1)))
  const input = useRef<HTMLTextAreaElement>(null)
  // The input grows with the question, up to its max height: a spoken question is often two lines.
  useLayoutEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + 2}px`
  }, [draft])
  const micShown = voiceSupported && !draft.trim()
  // The quick replies scroll sideways on a phone. While there is more to the right the row fades at its
  // right edge; at its end, and when it fits or wraps (a wide screen), it does not.
  const quickRow = useRef<HTMLDivElement>(null)
  const [quickMore, setQuickMore] = useState(false)
  const measureQuick = () => {
    const row = quickRow.current
    setQuickMore(row !== null && scrollsFurther(row.scrollLeft, row.scrollWidth, row.clientWidth))
  }
  useLayoutEffect(measureQuick) // after every render: «Создать заявку» comes and goes, the row hides while typing
  useEffect(() => {
    window.addEventListener('resize', measureQuick)
    return () => window.removeEventListener('resize', measureQuick)
  }, [])
  // Where focus goes when the ticket sheet is gone and the button that opened it is gone too: «Открыть
  // заявку» when the draft still waits, else the question field. Not the field on a touch screen: the
  // keyboard would come up over the ticket.
  const openTicket = useRef<HTMLButtonElement>(null)
  const afterTicket = () =>
    openTicket.current ?? (window.matchMedia('(pointer: coarse)').matches ? null : input.current)
  // Tickets of this vehicle as the server has them now: made in any thread, with their outcomes.
  const [tickets, setTickets] = useState<TicketView[]>([])
  // Tickets saved or sent on this screen since the list was asked for: newer than their copies in it.
  const touched = useRef(new Set<number>())
  const upsertTicket = (ticket: TicketView) => {
    touched.current.add(ticket.id)
    setTickets((list) => withTicket(list, ticket))
    onTicketsChanged?.()
  }
  const thread = useThread(vehicleId, attempt)
  const lastUser = useRef<HTMLParagraphElement>(null)
  // A restored conversation is about a check of its own: the picker shows that check, not the latest,
  // until the mechanic picks another.
  const picked = useRef(false)
  const pick = (id: string) => {
    picked.current = true
    setSessionId(id)
  }
  const restored = thread.sessionId
  useEffect(() => {
    if (!picked.current && restored && vehicle?.sessions.some((s) => s.session_id === restored)) {
      setSessionId(restored)
    }
  }, [restored, vehicle])

  useEffect(() => {
    let stale = false
    touched.current = new Set()
    getTickets(vehicleId)
      .then((list) => !stale && setTickets((local) => mergeTickets(local, list, touched.current)))
      .catch(() => {}) // the screen works without the earlier tickets
    getVehicle(vehicleId)
      .then((v) => {
        if (stale) return
        setVehicle(v)
        setSessionId(v.sessions[v.sessions.length - 1]?.session_id ?? null)
      })
      .catch((e) => !stale && setProblem(e instanceof ApiError && e.status === 404 ? 'missing' : 'failed'))
    return () => {
      stale = true
    }
  }, [vehicleId, attempt])

  // A new question goes to the top of the view, so the verdict and the start of the answer stay in
  // sight while the rest streams in below. The view never chases the stream.
  // The browser would chase it for us: once the thread has been scrolled, its scroll anchoring moves the
  // view down with every piece of the answer, and the question ends far above the view. So anchoring
  // is off for the thread while an answer runs (`anchoringWhile` on the scroll area below), and only then.
  const turnCount = thread.turns.length
  useEffect(() => {
    lastUser.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [turnCount])

  // Loading, failed, no such vehicle, no checks: each says what it is, under the bar with the way back.
  if (!vehicle || sessionId === null) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <Header title={vehicleId} onBack={onBack} />
        <div className="mx-auto w-full max-w-3xl space-y-3 p-4">
          {vehicle ? (
            <p className="text-dim">{copy.vehicle.noChecks}</p>
          ) : problem === 'missing' ? (
            <p role="alert">{copy.fleet.empty}</p>
          ) : problem === 'failed' ? (
            <div className="space-y-3" role="alert">
              <p>{copy.vehicle.loadFailed}</p>
              <button
                type="button"
                onClick={() => {
                  setProblem(null)
                  setAttempt((n) => n + 1)
                }}
                className="min-h-12 rounded-lg border border-line px-4"
              >
                {copy.retry}
              </button>
            </div>
          ) : (
            <p className="text-dim" role="status">
              {copy.vehicle.loading}
            </p>
          )}
        </div>
      </div>
    )
  }

  const send = (message: string, newThread = false, level?: Level) => {
    if (thread.busy || !message.trim()) return
    setDraft('')
    // On a phone the keyboard would cover the answer, so the field lets go of it. With a real keyboard
    // the field stays ready for the next question.
    if (window.matchMedia('(pointer: coarse)').matches) input.current?.blur()
    // «подробнее» / «короче» — словами или голосом — меняют уровень только для этого ответа (#17)
    void thread.send(message.trim(), { sessionId, newThread, level: level ?? redoLevel(message) ?? undefined })
  }
  const manualNames = Object.fromEntries(vehicle.manuals.map((m) => [m.id, m.short]))
  const session = vehicle.sessions.find((s) => s.session_id === sessionId)
  const checkLabel = session ? `${session.session_id}, ${dateTimeRu(session.checked_at)}` : sessionId
  const blocksNewestFirst = [...thread.turns]
    .reverse()
    .flatMap((t) => (t.role === 'assistant' ? [...t.blocks].reverse() : []))
  const verdictAt = blocksNewestFirst.findIndex((b) => b.kind === 'verdict')
  const lastVerdict = blocksNewestFirst[verdictAt] as VerdictBlock | undefined
  // The guide of the current check is the one that came after its verdict. When the engine has no such
  // unit, no ticket is offered: the server would refuse it (spec §3, invariant 9).
  const guide = blocksNewestFirst.slice(0, Math.max(verdictAt, 0)).find((b) => b.kind === 'guide') as
    GuideBlock | undefined
  const lastUserIndex = thread.turns.findLastIndex((t) => t.role === 'user')
  const inThread = new Set(thread.turns.flatMap((t) => (t.role === 'ticket' ? [t.ticket.id] : [])))
  const earlier = tickets.filter((t) => !inThread.has(t.id)) // made in another conversation
  const ticketed = tickets.some((t) => t.session_id === lastVerdict?.session_id)
  const canTicket =
    lastVerdict?.status === 'anomaly' && guide?.coverage !== 'not_covered' && !thread.pending && !ticketed
  const ticketOpen = thread.pending !== null && thread.pending.pending_id !== dismissed
  const typing = draft.trim() !== '' // a stray space or an empty dictation is not a question being typed

  const showTurn = (turn: Turn, i: number) =>
    turn.role === 'user' ? (
      <p
        key={i}
        ref={i === lastUserIndex ? lastUser : undefined}
        className="ml-auto w-fit max-w-[85%] scroll-mt-4 rounded-xl bg-surface-2 px-3.5 py-2.5"
      >
        {turn.text}
      </p>
    ) : turn.role === 'ticket' ? (
      <TicketCard
        key={i}
        ticket={tickets.find((t) => t.id === turn.ticket.id) ?? turn.ticket}
        onChange={upsertTicket}
        onOpenSource={openSource}
        vehicle={vehicle}
      />
    ) : (
      <AssistantBlock
        key={i}
        turn={turn}
        sources={thread.sources}
        onOpenSource={openSource}
        manualNames={manualNames}
        onRedo={i === thread.turns.length - 1 && !thread.busy ? (l) => send(REDO[l].message, false, l) : undefined}
      />
    )
  const earlierTurns = lastUserIndex < 0 ? thread.turns : thread.turns.slice(0, lastUserIndex)
  const lastExchange = lastUserIndex < 0 ? [] : thread.turns.slice(lastUserIndex)
  const pendingBar = thread.pending && !ticketOpen && (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-accent/50 bg-surface px-4 py-3">
      <p>{copy.ticket.pending}</p>
      <button
        ref={openTicket}
        type="button"
        onClick={() => setDismissed(null)}
        className="min-h-12 shrink-0 font-semibold text-accent"
      >
        {copy.ticket.open}
      </button>
    </div>
  )

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* A slim bar stays; the vehicle details, the checks and the button scroll away with the thread. */}
      <Header
        onBack={onBack}
        title={
          <>
            {vehicle.vehicle_id} <span className="font-normal text-dim">· {vehicle.model ?? vehicle.make}</span>
          </>
        }
      >
        {thread.turns.length > 0 && (
          <button
            type="button"
            data-waits
            disabled={thread.busy}
            onClick={() => send(copy.vehicle.diagnose, true)}
            className="min-h-12 shrink-0 pl-2 text-[13px] text-accent enabled:hover:underline disabled:opacity-50"
          >
            {copy.vehicle.newThread}
          </button>
        )}
      </Header>

      {/* A size container: the last exchange below takes its height from this view (.last-exchange). */}
      {/* `data-thread`: a sheet beside the thread passes the wheel and a press on a chip on to it (Sheet.tsx).
          `data-waits`, on the controls around the thread: they are drawn quieter meanwhile (index.css). */}
      <div
        data-thread
        className={`min-h-0 flex-1 overflow-y-auto [container-type:size] ${anchoringWhile(thread.busy)}`}
      >
        <div className="mx-auto max-w-3xl space-y-5 p-4">
          <section className="space-y-3">
            <p className="text-[13px] text-dim">
              {vehicle.garage_no} · {copy.vehicle.engine} {vehicle.engine_model} · {copy.vehicle.manuals}:{' '}
              {vehicle.manuals.map((m) => m.short).join(', ')}
            </p>
            <ScoreChart sessions={vehicle.sessions} selected={sessionId} onSelect={pick} trend={vehicle.trend} />
            <SessionPicker sessions={vehicle.sessions} selected={sessionId} onSelect={pick} />
            <button
              type="button"
              disabled={thread.busy}
              onClick={() => send(copy.vehicle.diagnose)}
              className="min-h-12 w-full rounded-lg bg-accent px-4 font-semibold text-bg enabled:hover:bg-accent/90 disabled:opacity-50 min-[900px]:w-auto min-[900px]:px-8"
            >
              {copy.vehicle.diagnose}
            </button>
          </section>
          {earlier.length > 0 && (
            <section className="space-y-3">
              <p className="text-[13px] text-dim">{copy.ticket.earlier}</p>
              {earlier.map((t) => (
                <TicketCard key={t.id} ticket={t} onChange={upsertTicket} onOpenSource={openSource} vehicle={vehicle} />
              ))}
            </section>
          )}
          {earlierTurns.map(showTurn)}
          {/* The last question and everything after it are at least one view tall (less the 16 px above
              the question and below the thread), while the answer runs and after it ends. So the question
              can reach the top of the view, and nothing moves when the answer is complete. */}
          {lastExchange.length > 0 && (
            <div className="last-exchange space-y-5">
              {lastExchange.map((turn, k) => showTurn(turn, lastUserIndex + k))}
              {pendingBar}
            </div>
          )}
          {lastExchange.length === 0 && pendingBar}
        </div>
      </div>

      <footer className="border-t border-line bg-bg pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
        {/* the sides' 16 px are the column's, as in the thread: the field and the chips keep its edges */}
        <div className="mx-auto max-w-3xl space-y-2 px-4">
          {/* While the mechanic types, the ready-made questions step aside: the keyboard has taken half
              the screen, and the answer above needs the room. «Создать заявку» is not one of them: it
              stays whatever is in the field (ТЗ F7). */}
          {(canTicket || !typing) && (
            <div
              ref={quickRow}
              data-waits
              onScroll={measureQuick}
              className={`no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 min-[900px]:flex-wrap ${quickMore ? 'fade-right' : ''}`}
            >
              {canTicket && (
                <button
                  type="button"
                  disabled={thread.busy}
                  onClick={() => send(copy.thread.createTicketMessage)}
                  className="min-h-12 shrink-0 rounded-lg border border-accent px-3 font-semibold text-accent enabled:hover:bg-accent/10 disabled:opacity-50"
                >
                  {copy.thread.createTicket}
                </button>
              )}
              {!typing &&
                copy.thread.quick.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={thread.busy}
                    onClick={() => send(q)}
                    className="min-h-12 shrink-0 rounded-lg border border-line px-3 text-[13px] text-dim hover:text-text disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
            </div>
          )}
          <LevelSwitch />
          {voice.error && (
            <p role="status" className="text-[13px] text-warn">
              {voice.error}
            </p>
          )}
          <form
            data-waits
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send(draft)
            }}
          >
            <textarea
              ref={input}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value)
                voice.clearError()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  send(draft)
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder={
                voice.state === 'recording'
                  ? copy.thread.voice.listening
                  : voice.state === 'sending'
                    ? copy.thread.voice.sending
                    : copy.thread.placeholder
              }
              aria-label={copy.thread.placeholder}
              className="max-h-32 min-h-12 flex-1 resize-none rounded-lg border border-line bg-surface-2 px-3 py-3 placeholder:text-mute"
            />
            {micShown ? (
              <button
                type="button"
                onClick={voice.toggle}
                disabled={voice.state === 'sending'}
                aria-label={voice.state === 'recording' ? copy.thread.voice.stop : copy.thread.voice.start}
                aria-pressed={voice.state === 'recording'}
                className={`grid size-12 shrink-0 place-items-center rounded-lg border enabled:hover:text-accent disabled:opacity-40 ${
                  voice.state === 'recording' ? 'border-stop bg-stop text-bg' : 'border-line bg-surface-2 text-text'
                }`}
              >
                {voice.state === 'recording' ? (
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
                    <rect x="5" y="5" width="10" height="10" rx="2" />
                  </svg>
                ) : (
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    aria-hidden
                  >
                    <rect x="7" y="2.5" width="6" height="9.5" rx="3" />
                    <path d="M4 9.5a6 6 0 0 0 12 0M10 15.5v2.5" />
                  </svg>
                )}
              </button>
            ) : (
              <button
                type="submit"
                disabled={thread.busy || !draft.trim()}
                aria-label={copy.thread.send}
                className="grid size-12 shrink-0 place-items-center rounded-lg bg-accent text-bg disabled:opacity-40"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden
                >
                  <path d="M10 16V4M5 9l5-5 5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </form>
        </div>
      </footer>

      {thread.pending && ticketOpen && (
        <TicketSheet
          key={thread.pending.pending_id}
          pending={thread.pending}
          hidden={source !== null}
          sources={thread.sources}
          checkLabel={checkLabel}
          onClose={() => setDismissed(thread.pending?.pending_id ?? null)}
          onCreated={(ticket) => {
            upsertTicket(ticket)
            thread.ticketCreated(ticket)
          }}
          onOpenSource={openSource}
          focusAfter={afterTicket}
        />
      )}
      {source && (
        <PageSheet
          key={`${source.manual_id}/${source.pdf_page}`}
          vehicleId={vehicleId}
          source={source}
          quote={quote}
          scanned={scanned}
          onClose={() => setSource(null)}
        />
      )}
    </div>
  )
}

/** «Как объяснять»: коротко (опытный механик) или по шагам — на этом устройстве, для следующих вопросов (#17). */
function LevelSwitch() {
  const [level, set] = useState<Level>(getLevel)
  useEffect(() => {
    const follow = () => set(getLevel())
    window.addEventListener(LEVEL_EVENT, follow)
    return () => window.removeEventListener(LEVEL_EVENT, follow)
  }, [])
  const pick = (l: Level) => {
    setLevel(l)
    set(l)
  }
  return (
    <div data-waits role="group" aria-label="Как объяснять" className="flex items-center gap-2 text-[13px] text-dim">
      <span className="shrink-0">Как объяснять:</span>
      {(['expert', 'steps'] as const).map((l) => (
        <button
          key={l}
          type="button"
          aria-pressed={level === l}
          onClick={() => pick(l)}
          className="min-h-12 flex-1 rounded-lg border border-line px-2 aria-pressed:border-accent aria-pressed:bg-surface-2 aria-pressed:text-text"
        >
          {l === 'expert' ? 'Коротко' : 'По шагам'}
        </button>
      ))}
    </div>
  )
}
