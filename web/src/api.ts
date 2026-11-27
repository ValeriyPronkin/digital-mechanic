// Shapes mirror app/schemas.py. One place for every call to the backend.
import { getLang, voiceLang } from './lib/lang'

import type { LevelChoice } from './lib/level'
import type { BuildInfo } from './lib/version'

export type Status = 'normal' | 'anomaly' | 'check_failed'
export type SignalQuality = 'good' | 'warning' | 'bad'
export type Urgency = 'low' | 'medium' | 'high'
export type FleetStatus = 'normal' | 'attention' | 'quarantine'

export interface SessionBrief {
  session_id: string
  checked_at: string
  status: Status
  anomaly_type: string | null
  anomaly_title: string | null
  anomaly_score: number | null
  signal_quality: SignalQuality
  // false: the check named a fault this engine cannot have; an error of the acoustic model, not an anomaly
  fits_engine?: boolean
}

export interface FleetStatusView {
  status: FleetStatus | null
  label: string | null
  badges: { code: string; label: string }[]
  urgency: Urgency | null
  session_id: string | null
  fault_title: string | null
  anomaly_score: number | null
  reason: string
}

export interface Vehicle {
  vehicle_id: string
  garage_no: string
  make: string
  model: string | null
  vehicle_type: string
  engine_model: string
  fuel: string
}

export interface VehicleBrief extends Vehicle {
  sessions_count: number
  last_session: SessionBrief | null
  fleet: FleetStatusView
}

export interface ManualBrief {
  id: string
  short: string
  title: string
  pages: number
}

export interface VehicleDetail extends Vehicle {
  sessions: SessionBrief[]
  manuals: ManualBrief[]
  fleet: FleetStatusView
  trend: string
}

export interface FleetView {
  counts: Record<FleetStatus | 'no_valid_check', number>
  vehicles: VehicleBrief[] // in the order a chief mechanic deals with them
  outcomes: { tickets: number; recorded: number; confirmed: number } // what the inspections showed
}

export interface UrgencyView {
  level: Urgency
  word: string
  action: string // what the priority means for the vehicle; empty in threads saved before it existed
  reasons: string[]
}

export interface VerdictBlock {
  kind: 'verdict'
  // mismatch: the check named a fault this engine cannot have; an error of the acoustic model, no priority
  case: 'normal' | 'normal_raised' | 'anomaly' | 'preliminary' | 'failed' | 'mismatch'
  headline: string
  lines: string[]
  session_id: string
  checked_at: string
  status: Status
  fault_code: string | null
  fault_title: string | null
  anomaly_score: number | null
  confidence: number | null
  confidence_word: string | null
  // The confidence below which the result is preliminary (the server's rule; 0,6 in data/danger_classes.json).
  // Absent from a server that does not send it: then the card says nothing about it.
  confidence_threshold?: number | null
  signal_quality: SignalQuality
  quality_word: string
  urgency: UrgencyView | null
  description: string
  foreign_text: string | null
  model_version: string
}

export interface ErrorBlock {
  kind: 'error'
  message: string
}

export type Coverage = 'covered' | 'general_inspection_only' | 'not_covered'

/** What this engine's manuals have on the fault of the current check (registry/coverage.yaml). */
export interface GuideBlock {
  kind: 'guide'
  coverage: Coverage
  fault_code: string
  fault_title: string
  proof: string | null
  proof_source: string | null
  recommendation: string | null // for not_covered: the text to take to a defect inspection instead of a ticket
  pages: { source: string; why: string }[]
}

/** Manuals disagree (our D-20): every wording verbatim with its page; the code builds it, not the model. */
export interface ContradictionBlock {
  kind: 'contradiction'
  title: string
  // note: a mark the code put on that page, e.g. «испытания на стенде»
  items: {
    handle: string | null
    label: string
    quote: string
    manual_id: string
    pdf_page: number
    note?: string | null
  }[]
  conclusion: string
  advice: string // since #93 the hand-over to the chief mechanic; before it, advice to ask the maker
  // since #93: the hand-over, its number on the chief mechanic's screen, and whether it is decided
  // number: null in a decided line of a server before the number was put into it
  escalation?: { line: string; number: number | null; resolved: boolean } | null
}

export type Block =
  VerdictBlock | GuideBlock | ErrorBlock | ContradictionBlock | { kind: string; [key: string]: unknown }

export interface SourceItem {
  handle: string
  manual_id: string
  short: string // the name the model reads; also the fallback for the chip
  chip?: string // the manual's name on a source chip; absent in threads stored before it existed
  designation: string
  pdf_page: number
}

export interface TicketItem {
  text: string
  source: string
  quote: string // the lines of the cited page the work was found in; empty in drafts saved before it existed
  scanned: boolean // the lines come from the machine reading of the page image
  // The page the work or part was found on: the manual by its id and designation (as in `references`), its
  // short name and the PDF page. Null when the server does not know the page; absent in older drafts.
  manual_id?: string | null
  manual?: string | null
  short?: string | null
  pdf_page?: number | null
}

/** A work or a part of a sent ticket with its page, kept beside the payload; ТОиР never gets it. */
export type TicketLine = TicketItem

export interface TicketPayload {
  vehicle_id: string
  session_id: string
  anomaly_type: string
  conclusion: string
  urgency: Urgency
  operations: string[]
  spare_parts: string[]
  references: { manual: string; pdf_page: number }[]
}

export interface TicketPending {
  pending_id: string
  payload: TicketPayload
  operations: TicketItem[]
  spare_parts: TicketItem[]
  urgency: UrgencyView // the proposed priority and why
  // The three the mechanic chooses from, each with what it means for the vehicle. Absent in a draft saved
  // before the choice existed: that one goes with the proposed priority.
  urgency_choices?: { level: Urgency; word: string; action: string }[]
  warning: string[] // why the result is preliminary; not empty means the mechanic must confirm he has read it
  // What the connected parts suppliers have for the parts of the draft (PR #84); null without parts, absent
  // in a draft saved before the field existed. For reference only: it does not go to ТОиР.
  parts_offers?: PartsOffers | null
}

/** One supplier's offer for a part, as the supplier gave it; the server sorts them (in stock, lead, price). */
export interface PartOffer {
  supplier: string | null
  name: string | null
  designation: string | null
  available: string | null // the supplier's own words: «есть, 12 шт.», «под заказ»
  in_stock: boolean | null // read from `available` by the server; null — not said
  price_rub: number | null
  lead_days: number | null
  url: string | null
}

/** The offers for one line of `payload.spare_parts` (by `index`). */
export interface PartOffersItem {
  index: number
  part: string
  query: string // what was looked for: the designation from the manual, or the name without it
  by: 'designation' | 'name'
  check: string // «по названию, проверьте» when looked up by name; empty otherwise
  note: string // why there is nothing: no supplier has it, or none answered
  offers: PartOffer[]
  suppliers: { name: string; status: 'ok' | 'empty' | 'failed'; note: string }[]
}

export interface PartsOffers {
  connected: boolean // false: no supplier is connected, `note` says so and `items` is empty
  note: string
  items: PartOffersItem[]
}

export interface TicketView {
  id: number
  ticket_id: string
  vehicle_id: string
  session_id: string
  created_at: string
  payload: TicketPayload // what was sent; its `urgency` is the mechanic's final choice
  urgency_proposed?: Urgency | null // what the server proposed; absent in threads saved before the choice
  // Each work and part with its own page, as sent. null or absent for a ticket stored before it was kept:
  // then only `payload.references`, the pages as one list.
  lines?: { operations: TicketLine[]; spare_parts: TicketLine[] } | null
  outcome: 'confirmed' | 'not_confirmed' | 'other_fault' | null
  outcome_note: string | null
}

export interface UsageEvent {
  model: string
  input_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  output_tokens: number
  latency_ms: number
  cost_usd: number
  cost_rub: number
  replayed: boolean
}

export interface ToolTrace {
  id?: string
  name: string
  label?: string
  ok?: boolean
  input?: Record<string, unknown>
}

/** A claim the server withdrew (app/verify.py). `reason` says why and `handles` are the pages it cited;
 *  an answer checked before the event carried them has neither, and `state` and the marks after the
 *  note in the text stand in. */
export interface WithdrawnClaim {
  text: string // the claim as the model wrote it, handles and list marker included
  state: string // unverified | uncited
  missing?: string[] // the numbers that were not found
  reason?: string | null // not_on_page | no_source | other_variant | page_number | hypothesis
  handles?: string[] // the marks shown after its note; none for a hypothesis
}

/** One group of marks of the checked text, as the server reads groups (`verify._MARK_GROUP`: a run of
 *  marks with nothing but whitespace between them), and for each page in it the line found for the
 *  numbers of the sentence the group follows. `quote` is null when that sentence confirmed no number on
 *  that page: a sentence without a number, the marks of a withdrawal note, a handle never issued. */
export interface ClaimMarks {
  handles: { handle: string; quote: string | null; scanned: boolean }[]
}

export interface Verification {
  verified: string[] // handles that supported at least one number
  quotes: Record<string, string> // handle → the line of the page the number was found on
  counts: { verified: number; unverified: number; uncited: number } // claims with numbers, by outcome
  withdrawn?: WithdrawnClaim[] // in the order of their notes in the checked text
  scanned?: string[] // handles whose number was found only in the machine reading of the page image
  // One item per group of marks in the checked text, in text order. Empty or absent for an answer checked
  // before the event carried it, and whenever the server could not line its items up with the text:
  // then `quotes` and `scanned`, one line per page, are what there is.
  claims?: ClaimMarks[]
}

/** Our request passport (issue #31): what the assistant did, what went to the model, what it cost. */
export interface PassportFragment {
  ref: string
  manual: string
  pdf_page: number
  section: string
  tokens: number
  used: boolean
  why_in?: string // why the page went to the model (since PR #177); absent in older passports
  why_out?: string | null // why it did not go into the answer; null — it did
}
export interface Passport {
  request_id: string | null
  question?: { text: string | null; by_voice: boolean; level: string | null } | null // novice | mechanic | master (#91)
  searches: { by: string; engine: string | null; queries: string[]; found: number; fragments: PassportFragment[] }[]
  llm: {
    name: string
    provider: string
    tokens_in: number
    tokens_cached: number
    tokens_out: number
    ms: number
    cost_rub: number
  }[]
  voice: { stt_seconds: number; stt_rub: number; tts_chars: number; tts_rub_estimate: number }
  rules: string[]
  total: {
    model_rub: number
    search_rub: number
    voice_rub: number
    total_rub: number
    ms: number
    fragments_tokens: number
    unused_tokens: number
    unused_share: number
  }
  // the passport in plain words (since PR #177): one line each; absent in older passports
  explain?: { cost?: string; tokens?: string; cached?: string; unused?: string }
}

/** The short spoken version of an answer (our #14): built by the code from the checked answer, every number
 *  from the page it cites; synthesized only with the server's signature (voice zahar, phrases cached). */
export interface SpeechInfo {
  text: string
  sig: string
  url: string
  lang?: string | null // the voice's language (PR #83); goes back to /api/voice/speak with the text
}

/** A language of the answer and what the voice can do in it (`GET /api/v2/languages`, SSE `language`). */
export interface LanguageInfo {
  lang: string // ru, uz, uz-cyrl, tg, kk, ky, en, hi
  name: string // in that language: «Oʻzbekcha»
  voice_input: boolean // speech recognition knows it; otherwise a question is said in Russian
  voice_output: boolean
}

export type TranscriptEntry =
  | { role: 'user'; text: string }
  | {
      role: 'assistant'
      text: string
      blocks: Block[]
      tools: ToolTrace[]
      usage: UsageEvent[]
      verification?: Verification
      passport?: Passport
      speech?: SpeechInfo
      back_translation?: string | null // the answer in Russian when it was given in another language
    }
  | { role: 'ticket'; ticket: TicketView }

/** A row of the vehicle's conversation history (#92). Times are ISO UTC. */
export interface ThreadRow {
  thread_id: string
  started_at: string | null
  updated_at: string | null
  session_id: string | null
  topic: string | null // the first question, without personal data, up to 80 characters
  status: 'open' | 'ticket_pending' | 'ticket_sent' | string
  ticket_id: string | null
  records: number // answers and tickets written for the warranty claim
}

export interface ThreadView {
  thread_id: string
  session_id: string | null
  transcript: TranscriptEntry[]
  sources: SourceItem[]
  pending: TicketPending | null
}

/** A rectangle on the page image: fractions of its width and height, from the top left corner. */
export interface PageMark {
  x: number
  y: number
  w: number
  h: number
}

export interface PageView {
  manual_id: string
  short: string
  designation: string
  page: number
  pages: number
  text: string
  image: string | null
  marks: PageMark[] // the printed line the quote is on; empty when the server could not name it for certain
  focus: PageMark | null // the first number of that line
}

/** A part or a tool in the answer (docs/api-v2-web.md §8): the server marks it by the registry of the manuals.
 *  `start`/`end` are code points in the text of the event; `text` is the piece to colour. `page`, `manual_id`
 *  and `ref` only when the page is certain; `designation` only when it is in the manual. */
export interface AnswerSpan {
  type: 'part' | 'tool'
  text: string
  start: number
  end: number
  name: string
  designation: string | null
  page: number | null
  manual_id: string | null
  ref: string | null
}

export type ChatEvent =
  | { type: 'thread'; thread_id: string }
  | { type: 'tool_started'; id: string; name: string; label: string; input?: Record<string, unknown> }
  | { type: 'tool_result'; id: string; name: string; ok: boolean; block: Block | null }
  | { type: 'sources'; items: SourceItem[] }
  | { type: 'text'; text: string; round: number; level_used?: string; spans?: AnswerSpan[] }
  | ({ type: 'verification'; text: string } & Verification)
  | ({ type: 'ticket_pending' } & TicketPending)
  | ({ type: 'usage' } & UsageEvent)
  | ({ type: 'passport' } & Passport)
  | ({ type: 'speech' } & SpeechInfo)
  | ({ type: 'language' } & LanguageInfo)
  | { type: 'back_translation'; text: string }
  | { type: 'error'; message: string }
  | { type: 'done'; reason: string }

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => (typeof b?.detail === 'string' ? b.detail : null))
      .catch(() => null)
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export class ApiError extends Error {
  status: number
  detail: string | null
  constructor(status: number, detail: string | null) {
    super(detail ?? `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
})

export const getFleet = () => json<FleetView>('/api/v2/fleet')
/** `build` of /health (§7): the commit and the time of the build, for the footer. */
export const getBuild = () => json<{ build?: BuildInfo }>('/health').then((h) => h.build ?? null)
export const getLanguages = () => json<LanguageInfo[]>('/api/v2/languages')
export const getVehicle = (id: string) => json<VehicleDetail>(`/api/v2/vehicles/${encodeURIComponent(id)}`)
/** The check's card alone, from the ML fields and the server's rules, no model: it is ready in a fraction of a
 *  second, while the stand delivers the chat stream only whole. */
export const getVerdict = (vehicleId: string, sessionId: string) =>
  json<VerdictBlock>(
    `/api/v2/vehicles/${encodeURIComponent(vehicleId)}/verdict?session_id=${encodeURIComponent(sessionId)}`,
  )
export const getThread = (vehicleId: string) =>
  json<ThreadView | null>(`/api/v2/threads/current?vehicle_id=${encodeURIComponent(vehicleId)}`)
/** The vehicle's earlier conversations, newest first (#92): the mechanic comes back in an hour or in half a year. */
export const getThreads = (vehicleId: string) =>
  json<ThreadRow[]>(`/api/v2/vehicles/${encodeURIComponent(vehicleId)}/threads`)
/** Continue an earlier conversation on this phone: it becomes the current one, the next question goes to it. */
export const resumeThread = (threadId: string, vehicleId: string) =>
  json<ThreadView>(`/api/v2/threads/${encodeURIComponent(threadId)}/resume`, post({ vehicle_id: vehicleId }))
/** The record for a warranty claim: every answer with its pages, the model and the hash chain; `html` prints. */
export const exportUrl = (vehicleId: string, threadId: string, format: 'html' | 'json') =>
  `/api/v2/vehicles/${encodeURIComponent(vehicleId)}/threads/${encodeURIComponent(threadId)}/export?format=${format}`
/** A manual page; with `quote` (the line found on it) the server also says where that line is printed. */
export const getPage = (vehicleId: string, manualId: string, page: number, quote?: string) =>
  json<PageView>(
    `/api/v2/vehicles/${encodeURIComponent(vehicleId)}/pages/${manualId}/${page}` +
      (quote ? `?quote=${encodeURIComponent(quote)}` : ''),
  )

/** Voice input: the recording as the raw body, its words back. `lang` is the language it is recognized in
 *  (the mechanic's choice); the server takes Russian for one it cannot recognize. */
export const transcribe = (audio: Blob, lang = voiceLang(getLang())) =>
  json<{ text: string }>(`/api/v2/transcribe?lang=${encodeURIComponent(lang)}`, {
    method: 'POST',
    headers: { 'content-type': audio.type || 'audio/webm' },
    body: audio,
  })

export type Outcome = NonNullable<TicketView['outcome']>
export const getTickets = (vehicleId: string) =>
  json<TicketView[]>(`/api/v2/vehicles/${encodeURIComponent(vehicleId)}/tickets`)
/** `note` left out keeps the note the ticket has; an empty one removes it. */
export const setOutcome = (ticketPk: number, outcome: Outcome, note?: string) =>
  json<TicketView>(`/api/v2/tickets/${ticketPk}/outcome`, post({ outcome, note }))
export const OUTCOMES_EXPORT = '/api/v2/outcomes.csv'

/** A ticket in the chief mechanic's register (`GET /api/v2/tickets`): the ticket and what its row needs. */
export interface TicketRow extends TicketView {
  garage_no: string | null // null: the vehicle has left the fleet since
  vehicle_name: string | null
  engine_model: string | null
  checked_at: string | null // when the check the ticket is for was recorded
  fault_title: string // the name of `payload.anomaly_type`; the code if it has none
}
/** Every ticket of the fleet, newest first. */
export const getAllTickets = () => json<TicketRow[]>('/api/v2/tickets')

export const approveTicket = (
  pendingId: string,
  vehicleId: string,
  keepOperations: number[],
  keepParts: number[],
  warningAcknowledged: boolean,
  urgency?: Urgency, // the priority chosen on the sheet; left out, the proposed one is sent
) =>
  json<TicketView>(
    `/api/v2/tickets/${pendingId}/approve`,
    post({
      vehicle_id: vehicleId,
      keep_operations: keepOperations,
      keep_spare_parts: keepParts,
      warning_acknowledged: warningAcknowledged,
      urgency,
    }),
  )

export const rejectTicket = (pendingId: string, vehicleId: string) =>
  json<void>(`/api/v2/tickets/${pendingId}/reject`, post({ vehicle_id: vehicleId }))

/** POST /api/chat and deliver each server-sent event to `onEvent`. Resolves when the stream ends. */
export async function streamChat(
  body: {
    vehicle_id: string
    message: string
    session_id?: string | null
    new_thread?: boolean
    level?: LevelChoice // «auto»: the server picks per question (#91); a level only when the mechanic asked for it
    lang?: string // the language of the answer the mechanic chose; left out, the language of the question
  },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/v2/chat', { ...post(body), credentials: 'same-origin', signal })
  if (!res.ok || !res.body) throw new ApiError(res.status, null)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)) as ChatEvent)
      }
    }
  }
}

// ---------- the chief mechanic's queue of contradictions between manuals (#93, docs/api-v2-web.md §6) ----------

// known: in the registry of the manuals' contradictions, not yet met in an answer (needs the server's list)
export type ContradictionStatus = 'known' | 'open' | 'sent' | 'resolved'
export type LetterTo = 'manufacturer' | 'support'
export type ResolutionSource = LetterTo | 'chief_mechanic'

/** A hand-over to the maker or to support. The server does not send the letter: this is the mark that it went. */
export interface ContradictionSent {
  to: LetterTo
  by: string
  at: string
  text: string
  channel: string // `none`: no channel on the pilot, the chief mechanic sends the text himself
}

export interface ContradictionResolution {
  text: string
  by: string
  at: string
  source: ResolutionSource
  document: string | null
}

export interface ContradictionItem {
  number: number
  id: string
  status: ContradictionStatus
  engine: string
  title: string
  formulations: { label: string; manual_id: string; pdf_page: number; quote: string }[]
  rule: string | null
  safe_rule: string
  count: number // how many answers it came up in
  vehicles: string[]
  first_seen: string | null // null while known: no answer has met it yet
  last_seen?: string | null
  sent?: ContradictionSent[]
  resolution?: ContradictionResolution | null
}

export interface ContradictionLetter {
  to: LetterTo
  text: string
  channel: string
}

/** A line of the journal of decisions: only added to, with the hash of the line before it. */
export type ContradictionEvent = { number: number; id: string; seq: number; at: string; by: string } & (
  ({ event: 'sent' } & ContradictionSent) | ({ event: 'resolved' } & ContradictionResolution)
)

const CONTRADICTIONS = '/api/v2/contradictions'
export const getContradictions = (status: ContradictionStatus | 'all' = 'all') =>
  json<ContradictionItem[]>(`${CONTRADICTIONS}?status=${status}`)
export const getContradictionJournal = () => json<ContradictionEvent[]>(`${CONTRADICTIONS}/journal`)
export const getContradictionLetter = (number: number, to: LetterTo) =>
  json<ContradictionLetter>(`${CONTRADICTIONS}/${number}/letter?to=${to}`)
/** `text` only when the chief mechanic changed the draft: without it the server keeps its own. */
export const sendContradiction = (number: number, body: { to: LetterTo; by: string; text?: string }) =>
  json<ContradictionItem>(`${CONTRADICTIONS}/${number}/send`, post(body))
export const resolveContradiction = (
  number: number,
  body: { text: string; by: string; source: ResolutionSource; document?: string },
) => json<ContradictionItem>(`${CONTRADICTIONS}/${number}/resolve`, post(body))
