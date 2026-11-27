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
import { checkLook, ticketFits } from '../lib/checks'
import { dateShortRu, dateTimeRu } from '../lib/format'
import { shownBefore, verdictAnchor } from '../lib/verdict'
import { mergeTickets, withTicket } from '../lib/tickets'
import { CHECKED, scrollsFurther, scrollStep } from '../lib/ui'
import { useThread, type AssistantTurn, type Turn } from '../useThread'
import { ActionLog } from './ActionLog'
import { Answer } from './Answer'
import { ContradictionCard } from './ContradictionCard'
import { GuideCard } from './GuideCard'
import { ThreadHistory } from './ThreadHistory'
import { PageSheet } from './PageSheet'
import { SpeakButton } from './SpeakButton'
import { levelOf, moreDetail, redoLevel, shorter, type Level } from '../lib/level'
import { anchoringWhile } from '../lib/scroll'
import { ScoreChart } from './ScoreChart'
import { LanguageSwitch } from './LanguageSwitch'
import { offersRussian } from '../lib/lang'
import { TicketCard } from './TicketCard'
import { TicketSheet } from './TicketSheet'
import { VerdictCard } from './VerdictCard'
import { queueHref } from '../lib/contradictions'
import { Explain } from './Explain'
import { VersionFooter } from './VersionFooter'

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

/** The level an answer was given at: the text event's `level_used`, or the passport's for an answer stored
 *  before the event carried it. */
const answerLevel = (turn: AssistantTurn): Level | null =>
  levelOf(turn.level_used) ?? levelOf(turn.passport?.question?.level)

/** «По проверке S-0009 от 17 ноя: клапанный механизм ›» — the card of this check is already above in the
 *  conversation (Валерий, 27.11: the whole card again under every answer). A tap scrolls back to it. */
function VerdictAgain({ verdict: v }: { verdict: VerdictBlock }) {
  const what = v.fault_title ?? copy.verdict.word[v.case]
  return (
    <button
      type="button"
      onClick={() =>
        document.getElementById(verdictAnchor(v.session_id))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      title={copy.verdict.againHint}
      className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-line px-3 py-1.5 text-left text-[13px] text-dim hover:text-text"
    >
      <span className="min-w-0">
        {copy.verdict.again(v.session_id, dateShortRu(v.checked_at), what.charAt(0).toLowerCase() + what.slice(1))}
      </span>
      <svg
        width="16"
        height="16"
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 -rotate-90 text-accent"
        aria-hidden
      >
        <path d="M8 4l6 6-6 6" />
      </svg>
    </button>
  )
}

function AssistantBlock({
  turn,
  sources,
  onOpenSource,
  manualNames,
  onRedo,
  seenChecks,
}: {
  onRedo?: (level: Level) => void // the last answer only: «Подробнее / Короче» for this answer
  seenChecks: Set<string> // checks whose card an earlier turn shows: here they are one line (lib/verdict.ts)
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
      seenChecks.has((block as VerdictBlock).session_id) ? (
        <VerdictAgain key={key} verdict={block as VerdictBlock} />
      ) : (
        <div key={key} id={verdictAnchor((block as VerdictBlock).session_id)} className="scroll-mt-4">
          <VerdictCard verdict={block as VerdictBlock} />
        </div>
      )
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
  // manuals disagree: right under the direct answer («Коротко»), as the code put it there (D-20), and never
  // folded: Валерий did not see it at the end of a long answer (27.11)
  const found = turn.blocks.filter((b) => b.kind === 'contradiction')
  const contradictions = found.length > 0 && (
    <div className="space-y-3">
      {found.map((b, i) => (
        <ContradictionCard
          key={`c${i}`}
          block={b as ContradictionBlock}
          sources={sources}
          onOpen={(s, quote) => onOpenSource(s, quote)}
          onQueue={(n) => {
            window.location.hash = queueHref({ view: 'item', number: n })
          }}
        />
      ))}
    </div>
  )
  return (
    <div className="space-y-3">
      {turn.blocks.map((block, i) => (noModel && isGuide(block) ? null : show(block, i)))}
      {turn.text && (
        <Answer
          afterLead={contradictions || undefined}
          text={turn.text}
          spans={turn.spans}
          sources={sources}
          verified={new Set(turn.verification?.verified)}
          scanned={new Set(turn.verification?.scanned)}
          verification={turn.verification}
          onOpen={onOpenSource}
        />
      )}
      {/* An answer in another language, in Russian: for the one who checks it (PR #86). Its numbers were
          checked by the server; the chips are the same pages. */}
      {!turn.live && turn.back_translation && offersRussian(turn) && (
        <details className="group">
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 text-[13px] text-accent [&::-webkit-details-marker]:hidden">
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              className="shrink-0 transition-transform group-open:rotate-90"
              aria-hidden
            >
              <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {copy.lang.showRu}
          </summary>
          <div className="border-l-2 border-line pl-3">
            <Answer
              text={turn.back_translation}
              sources={sources}
              verified={new Set(turn.verification?.verified)}
              scanned={new Set(turn.verification?.scanned)}
              onOpen={onOpenSource}
            />
          </div>
        </details>
      )}
      {/* the level the server chose for this question, and the same question again a level down or up (#91);
          quiet, like the quick replies: «Создать заявку» stays the one accent action under an answer */}
      {(() => {
        const level = answerLevel(turn)
        if (!onRedo || turn.live || !turn.text || !level) return null
        const down = moreDetail(level)
        const up = shorter(level)
        const quiet =
          'min-h-12 rounded-lg border border-line px-3 text-dim hover:text-text min-[900px]:pointer-fine:min-h-9'
        return (
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <span className="mr-1 text-mute">{copy.level.answered[level]}</span>
            {down && (
              <button type="button" onClick={() => onRedo(down)} className={quiet}>
                {copy.level.more}
              </button>
            )}
            {up && (
              <button type="button" onClick={() => onRedo(up)} className={quiet}>
                {copy.level.shorter}
              </button>
            )}
            <Explain label={copy.level.explain} icon>
              <p>{copy.level.explainText}</p>
            </Explain>
          </div>
        )
      })()}
      {/* the short spoken version: value, document, page — for busy hands (#14) */}
      {!turn.live && turn.speech && <SpeakButton speech={turn.speech} />}
      {/* no answer text to stand under: the contradiction stands here, as before */}
      {!turn.text && contradictions}
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
/** The arrow on the edge of the row of ready-made questions: there are more that way. A round 36 px button
 *  over the row's end, on a band of the page's colour so it never sits on a question's text; the tap area
 *  is 48 px. Out of the tab order: the questions themselves are reached by Tab, and the row follows focus. */
function QuickArrow({ dir, label, onPress }: { dir: 1 | -1; label: string; onPress: () => void }) {
  return (
    <div
      className={`pointer-events-none absolute inset-y-0 flex items-center ${
        dir > 0
          ? '-right-4 bg-gradient-to-l pr-2 pl-6 min-[900px]:right-0 min-[900px]:pr-0'
          : '-left-4 bg-gradient-to-r pr-6 pl-2 min-[900px]:left-0 min-[900px]:pl-0'
      } from-bg from-55% to-transparent`}
    >
      <button
        type="button"
        tabIndex={-1}
        aria-label={label}
        title={label}
        onClick={onPress}
        className="pointer-events-auto relative grid size-9 place-items-center rounded-full border border-line bg-surface-2 text-accent before:absolute before:-inset-1.5 before:content-[''] hover:border-accent"
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d={dir > 0 ? 'M8 4l6 6-6 6' : 'M12 4l-6 6 6 6'} />
        </svg>
      </button>
    </div>
  )
}

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
  const [quickBack, setQuickBack] = useState(false)
  const measureQuick = () => {
    const row = quickRow.current
    setQuickMore(row !== null && scrollsFurther(row.scrollLeft, row.scrollWidth, row.clientWidth))
    setQuickBack(row !== null && row.scrollLeft > 1)
  }
  // The fade alone was not seen on a laptop (Валерий, 27.11): an arrow on the edge says the row goes on, and
  // a press moves it there. Mouse users have no swipe; on a phone the arrow is a second way to the same place.
  const scrollQuick = (dir: 1 | -1) => {
    const row = quickRow.current
    row?.scrollBy({ left: dir * scrollStep(row.clientWidth), behavior: 'smooth' })
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
  // «Обращения по машине»: asked again when an answer ends (a new conversation may have started)
  const [historyTick, setHistoryTick] = useState(0)
  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && !thread.busy) setHistoryTick((n) => n + 1)
    wasBusy.current = thread.busy
  }, [thread.busy])
  // An earlier conversation continued: the screen loads it as the current one, on its own check.
  const resumed = () => {
    picked.current = false
    setHistoryTick((n) => n + 1)
    setAttempt((n) => n + 1)
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
    const lastAnswer = thread.turns.findLast((t): t is AssistantTurn => t.role === 'assistant')
    const lastLevel = lastAnswer ? answerLevel(lastAnswer) : null
    // «подробнее» / «короче», typed or said, move from the level of the last answer, for this question only;
    // any other question goes without a level, and the server picks it (#91)
    void thread.send(message.trim(), {
      sessionId,
      newThread,
      level: level ?? redoLevel(message, lastLevel) ?? undefined,
    })
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
  const verdictCheck = vehicle.sessions.find((s) => s.session_id === lastVerdict?.session_id)
  // not for a result that does not fit the engine, nor for a unit the engine has not (lib/checks.ts)
  const canTicket = ticketFits(lastVerdict, verdictCheck, guide?.coverage) && !thread.pending && !ticketed
  const ticketOpen = thread.pending !== null && thread.pending.pending_id !== dismissed
  const typing = draft.trim() !== '' // a stray space or an empty dictation is not a question being typed

  // the check's card is drawn whole once; a later turn about the same check carries one line back to it
  const seenBefore = shownBefore(thread.turns.map((t) => (t.role === 'assistant' ? t.blocks : [])))
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
        seenChecks={seenBefore[i] ?? new Set()}
        onRedo={i === thread.turns.length - 1 && !thread.busy ? (l) => send(copy.level.ask[l], false, l) : undefined}
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
            {/* set once on the device, so it scrolls away with the vehicle details */}
            <LanguageSwitch />
            <button
              type="button"
              disabled={thread.busy}
              onClick={() => send(copy.vehicle.diagnose)}
              className="min-h-12 w-full rounded-lg bg-accent px-4 font-semibold text-bg enabled:hover:bg-accent/90 disabled:opacity-50 min-[900px]:w-auto min-[900px]:px-8"
            >
              {copy.vehicle.diagnose}
            </button>
          </section>
          <ThreadHistory
            vehicleId={vehicleId}
            currentId={thread.threadId}
            refresh={historyTick}
            disabled={thread.busy}
            onResumed={resumed}
          />
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
          {/* the version the jury looks at (§7), at the very end of the thread, out of the way */}
          <VersionFooter className="pt-2" />
        </div>
      </div>

      <footer className="border-t border-line bg-bg pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
        {/* the sides' 16 px are the column's, as in the thread: the field and the chips keep its edges */}
        <div className="mx-auto max-w-3xl space-y-2 px-4">
          {/* While the mechanic types, the ready-made questions step aside: the keyboard has taken half
              the screen, and the answer above needs the room. «Создать заявку» is not one of them: it
              stays whatever is in the field (ТЗ F7). */}
          {/* On a laptop the ready-made questions are one row of 36 px controls that scrolls sideways (the wheel
              too) instead of wrapping: four of them in two rows and the field took about 200 of 694 px and
              covered the card. On a phone — as before. The composer is the questions and the field, nothing
              else: the level is chosen per question by the server, and changed under the answer (#91). */}
          <div className="space-y-2 min-[900px]:flex min-[900px]:items-center min-[900px]:gap-3 min-[900px]:space-y-0">
            {(canTicket || !typing) && (
              <div className="relative min-[900px]:min-w-0 min-[900px]:flex-1">
                <div
                  ref={quickRow}
                  data-waits
                  onScroll={measureQuick}
                  onWheel={(e) => {
                    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) e.currentTarget.scrollLeft += e.deltaY
                  }}
                  className={`no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 min-[900px]:mx-0 min-[900px]:px-0 ${quickMore ? 'fade-right' : ''}`}
                >
                  {canTicket && (
                    <button
                      type="button"
                      disabled={thread.busy}
                      onClick={() => send(copy.thread.createTicketMessage)}
                      className="min-h-12 shrink-0 rounded-lg border border-accent px-3 font-semibold text-accent enabled:hover:bg-accent/10 disabled:opacity-50 min-[900px]:pointer-fine:min-h-9 min-[900px]:pointer-fine:text-[13px]"
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
                        className="min-h-12 shrink-0 rounded-lg border border-line px-3 text-[13px] text-dim hover:text-text disabled:opacity-50 min-[900px]:pointer-fine:min-h-9"
                      >
                        {q}
                      </button>
                    ))}
                </div>
                {quickBack && <QuickArrow dir={-1} label={copy.thread.quickPrev} onPress={() => scrollQuick(-1)} />}
                {quickMore && <QuickArrow dir={1} label={copy.thread.quickNext} onPress={() => scrollQuick(1)} />}
              </div>
            )}
          </div>
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
