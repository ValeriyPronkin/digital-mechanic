import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getThread,
  streamChat,
  type Block,
  type ChatEvent,
  type SourceItem,
  type TicketPending,
  type TicketView,
  type ToolTrace,
  type UsageEvent,
  type Verification,
} from './api'
import { copy } from './copy'

export interface AssistantTurn {
  role: 'assistant'
  text: string
  blocks: Block[]
  tools: ToolTrace[]
  usage: UsageEvent[]
  verification?: Verification
  progress?: string // the line shown while a tool runs
  error?: string
  reason?: string
  live?: boolean
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
        progress: e.label,
        tools: [...turn.tools, { id: e.id, name: e.name, label: e.label, input: e.input }],
      }
    case 'tool_result':
      return {
        ...turn,
        tools: turn.tools.map((t) => (t.id === e.id ? { ...t, ok: e.ok } : t)),
        blocks: e.block ? [...turn.blocks, e.block] : turn.blocks,
      }
    case 'text':
      return { ...turn, text: turn.text + e.text, progress: undefined }
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
    async (message: string, options: { sessionId?: string | null; newThread?: boolean } = {}) => {
      const live: AssistantTurn = {
        role: 'assistant',
        text: '',
        blocks: [],
        tools: [],
        usage: [],
        live: true,
        progress: copy.thread.working,
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
          { vehicle_id: vehicleId, message, session_id: options.sessionId, new_thread: options.newThread },
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
