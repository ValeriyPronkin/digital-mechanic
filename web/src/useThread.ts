import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getThread,
  getVerdict,
  streamChat,
  type AnswerSpan,
  type Block,
  type ChatEvent,
  type SourceItem,
  type TicketPending,
  type TicketView,
  type ToolTrace,
  type UsageEvent,
  type Passport,
  type SpeechInfo,
  type Verification,
  type LanguageInfo,
} from './api'
import { copy } from './copy'
import type { LevelChoice } from './lib/level'
import { chatLang, getLang } from './lib/lang'
import { isVerdictOf, shownVerdict, withVerdict } from './lib/verdict'

export interface AssistantTurn {
  role: 'assistant'
  text: string
  blocks: Block[]
  tools: ToolTrace[]
  usage: UsageEvent[]
  verification?: Verification
  passport?: Passport // our request passport (#31): steps, context, tokens, ₽
  speech?: SpeechInfo // the short spoken version (#14) for «Прослушать»
  language?: LanguageInfo // the language the answer was given in (PR #83)
  back_translation?: string | null // the answer in Russian when it is in another language: «Показать по-русски»
  progress?: string // the line shown while a tool runs
  error?: string
  reason?: string
  live?: boolean
  level_used?: string // the level the server answered at (#91); also in a restored transcript
  spans?: AnswerSpan[] // parts and tools in the answer, for their colours (§8); not in a restored transcript yet
}
export type Turn = { role: 'user'; text: string } | AssistantTurn | { role: 'ticket'; ticket: TicketView }

interface State {
  turns: Turn[]
  sources: Record<string, SourceItem>
  pending: TicketPending | null
  busy: boolean
  loaded: boolean
  sessionId: string | null // the check the restored conversation is about
}

const EMPTY: State = { turns: [], sources: {}, pending: null, busy: false, loaded: false, sessionId: null }
const bySource = (items: SourceItem[]) => Object.fromEntries(items.map((s) => [s.handle, s]))

function apply(turn: AssistantTurn, e: ChatEvent): AssistantTurn {
  switch (e.type) {
    case 'tool_started': // any text before a tool call was a preamble, not the answer
      return {
        ...turn,
        text: '',
        spans: undefined,
        progress: e.label,
        tools: [...turn.tools, { id: e.id, name: e.name, label: e.label, input: e.input }],
      }
    case 'tool_result': {
      const block = e.block
      return {
        ...turn,
        tools: turn.tools.map((t) => (t.id === e.id ? { ...t, ok: e.ok } : t)),
        // the card may already be here from its quick request: the stream's copy takes its place, not a second one
        blocks: !block
          ? turn.blocks
          : isVerdictOf(block, null)
            ? withVerdict(turn.blocks, block)
            : [...turn.blocks, block],
      }
    }
    case 'text':
      return {
        ...turn,
        text: turn.text + e.text,
        spans: e.spans ? [...(turn.spans ?? []), ...e.spans] : turn.spans,
        progress: undefined,
        level_used: e.level_used ?? turn.level_used,
      }
    case 'verification': // the checked text replaces the streamed one: failed claims are withdrawn
      return {
        ...turn,
        text: e.text,
        verification: {
          verified: e.verified,
          quotes: e.quotes,
          counts: e.counts,
          withdrawn: e.withdrawn,
          scanned: e.scanned,
          claims: e.claims,
        },
      }
    case 'usage':
      return { ...turn, usage: [...turn.usage, e] }
    case 'passport': {
      const { type: _, ...passport } = e
      return { ...turn, passport }
    }
    case 'speech': {
      const { type: _, ...speech } = e
      return { ...turn, speech }
    }
    case 'language': {
      const { type: _, ...language } = e
      return { ...turn, language }
    }
    case 'back_translation':
      return { ...turn, back_translation: e.text }
    case 'error':
      return { ...turn, error: e.message, progress: undefined }
    case 'done': {
      const reason = turn.reason ?? e.reason
      // Words of a turn the model did not finish were never checked against the pages: they go.
      const text = reason === 'model_unavailable' || reason === 'refusal' ? '' : turn.text
      return { ...turn, text, reason, live: false, progress: undefined }
    }
    default:
      return turn
  }
}

/** The conversation about one vehicle: restored on load, updated event by event while the agent works.
 *  The screen that uses it is keyed by vehicle, so a new vehicle starts from an empty state.
 *  `attempt` grows when the screen is loaded again after a failure: the conversation is fetched again too. */
export function useThread(vehicleId: string, attempt = 0) {
  const [state, setState] = useState<State>(EMPTY)
  const abort = useRef<AbortController | null>(null)
  const turnsNow = useRef<Turn[]>([]) // the turns of the last render, for `send` to read without a stale closure
  turnsNow.current = state.turns

  useEffect(() => {
    let stale = false
    getThread(vehicleId)
      .then((view) => {
        if (stale) return
        setState({
          turns: (view?.transcript ?? []) as Turn[],
          sources: bySource(view?.sources ?? []),
          pending: view?.pending ?? null,
          busy: false,
          loaded: true,
          sessionId: view?.session_id ?? null,
        })
      })
      .catch(() => !stale && setState({ ...EMPTY, loaded: true }))
    return () => {
      stale = true
      abort.current?.abort()
    }
  }, [vehicleId, attempt])

  const send = useCallback(
    async (message: string, options: { sessionId?: string | null; newThread?: boolean; level?: LevelChoice } = {}) => {
      const live: AssistantTurn = {
        role: 'assistant',
        text: '',
        blocks: [],
        tools: [],
        usage: [],
        live: true,
        progress: copy.thread.working,
      }
      // The card of the check, by its own quick request next to the chat: the stand sends the chat only when the
      // whole answer is ready, the card is ready at once. Asked only when this check has no card on the screen.
      const sessionId = options.sessionId ?? null
      const before = options.newThread ? [] : turnsNow.current
      const at = before.length + 1 // where this answer's turn will stand: after the question
      if (
        sessionId &&
        !shownVerdict(
          before.map((t) => (t.role === 'assistant' ? t.blocks : [])),
          sessionId,
        )
      ) {
        getVerdict(vehicleId, sessionId)
          .then((card) =>
            setState((s) => {
              const turn = s.turns[at]
              if (turn?.role !== 'assistant') return s // the conversation has moved on
              const turns = [...s.turns]
              turns[at] = { ...turn, blocks: withVerdict(turn.blocks, card) }
              return { ...s, turns }
            }),
          )
          .catch(() => {}) // no quick card: the chat brings it as before
      }
      setState((s) => ({
        ...s,
        busy: true,
        pending: null,
        turns: [...(options.newThread ? [] : s.turns), { role: 'user', text: message }, live],
        sources: options.newThread ? {} : s.sources,
      }))
      const onEvent = (e: ChatEvent) =>
        setState((s) => {
          if (e.type === 'sources') return { ...s, sources: { ...s.sources, ...bySource(e.items) } }
          if (e.type === 'ticket_pending') return { ...s, pending: e }
          const last = s.turns[s.turns.length - 1]
          if (last?.role !== 'assistant') return s
          return { ...s, turns: [...s.turns.slice(0, -1), apply(last, e)] }
        })
      abort.current = new AbortController()
      try {
        await streamChat(
          {
            vehicle_id: vehicleId,
            message,
            session_id: options.sessionId,
            new_thread: options.newThread,
            level: options.level ?? 'auto', // the server picks per question unless the mechanic asked for one
            lang: chatLang(getLang()),
          },
          onEvent,
          abort.current.signal,
        )
      } catch {
        onEvent({ type: 'error', message: copy.thread.failed })
      } finally {
        onEvent({ type: 'done', reason: 'closed' })
        setState((s) => ({ ...s, busy: false }))
      }
    },
    [vehicleId],
  )

  const ticketCreated = useCallback((ticket: TicketView) => {
    setState((s) => ({ ...s, pending: null, turns: [...s.turns, { role: 'ticket', ticket }] }))
  }, [])

  return { ...state, send, ticketCreated }
}
