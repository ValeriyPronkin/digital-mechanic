import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  getContradictionJournal,
  getContradictionLetter,
  getContradictions,
  resolveContradiction,
  sendContradiction,
  type ContradictionEvent,
  type ContradictionItem,
  type ContradictionStatus,
  type LetterTo,
  type ResolutionSource,
} from '../api'
import { copy } from '../copy'
import {
  editedText,
  firstStatus,
  knownEvents,
  moscowTime,
  queueCounts,
  queueHref,
  shownItems,
  STATUSES,
  type QueueRoute,
} from '../lib/contradictions'
import { plural } from '../lib/format'
import { CHECKED } from '../lib/ui'

const q = copy.queue
const FIELD = 'w-full rounded-lg border border-line bg-surface-2 px-3 py-2.5 placeholder:text-mute'
const BUTTON = 'min-h-12 rounded-lg border border-line px-4 hover:bg-surface disabled:opacity-60'
const PRIMARY = 'min-h-12 rounded-lg bg-accent px-4 font-semibold text-bg disabled:opacity-60'
const toneOf = { open: 'text-warn', sent: 'text-dim', resolved: 'text-ok' } as const

function Chevron({ back = false }: { back?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={back ? '' : 'shrink-0 text-accent'}
      aria-hidden
    >
      <path d={back ? 'M12 4l-6 6 6 6' : 'M8 4l6 6-6 6'} />
    </svg>
  )
}

/** Choices in one row, as the register's filters: a radiogroup of buttons. */
function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: ReactNode }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex gap-2" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-12 flex-1 rounded-lg border border-line px-2 text-[15px] text-dim ${CHECKED}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** The chief mechanic's way into the queue, beside the outcomes row of the fleet list: how many are open,
 *  sent and resolved. FleetList shows it only when the queue has something in it. */
export function QueueRow({ counts }: { counts: Record<ContradictionStatus, number> }) {
  return (
    <a
      href={queueHref({ view: 'list' })}
      className="mx-4 flex min-h-12 items-center justify-between gap-3 rounded-lg border border-line px-3 py-1 text-[13px] leading-[1.25] hover:bg-surface"
    >
      <span className="min-w-0">
        <span className={`block ${counts.open > 0 ? 'text-warn' : ''}`}>{q.open}</span>
        <span className="block text-dim">{q.openHint(counts.open, counts.sent, counts.resolved)}</span>
      </span>
      <Chevron />
    </a>
  )
}

function Row({ item }: { item: ContradictionItem }) {
  return (
    <a
      href={queueHref({ view: 'item', number: item.number })}
      className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface"
    >
      <span className="min-w-0 flex-1">
        <span className="block">
          <span className="font-semibold">{q.number(item.number)}</span> {item.title}
        </span>
        <span className="mt-0.5 block text-[13px] text-dim">
          {item.engine} · {q.seen(item.count, plural(item.count, q.times))}
          {item.last_seen && ` · ${moscowTime(item.last_seen)}`}
        </span>
        <span className={`mt-0.5 block text-[13px] ${toneOf[item.status]}`}>{q.state[item.status]}</span>
      </span>
      <Chevron />
    </a>
  )
}

function List({ items }: { items: ContradictionItem[] }) {
  const counts = queueCounts(items)
  const [show, setShow] = useState<ContradictionStatus>(() => firstStatus(counts))
  const rows = shownItems(items, show)
  return (
    <>
      {items.length === 0 ? (
        <p className="p-4 text-dim">{q.empty}</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 px-4 pt-3 pb-2" role="radiogroup" aria-label={q.show}>
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={show === s}
                onClick={() => setShow(s)}
                className="flex min-h-12 flex-col items-start rounded-lg border border-line px-3 py-1.5 text-left aria-checked:border-accent aria-checked:bg-surface-2"
              >
                <span className="text-[17px] leading-tight font-semibold">{counts[s]}</span>
                <span className={`text-[13px] leading-tight ${toneOf[s]}`}>{q.filter[s]}</span>
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="border-t border-line p-4 text-dim">{q.emptyFilter[show]}</p>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {rows.map((i) => (
                <li key={i.number}>
                  <Row item={i} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="px-4 pt-4 pb-6">
        <a
          href={queueHref({ view: 'journal' })}
          className="flex min-h-12 items-center justify-between gap-3 rounded-lg border border-line px-3 py-1.5 text-[13px] leading-[1.25] hover:bg-surface"
        >
          <span className="min-w-0">
            <span className="block">{q.journal}</span>
            <span className="block text-dim">{q.journalHint}</span>
          </span>
          <Chevron />
        </a>
      </div>
    </>
  )
}

/** The letter to the maker or to support: the server's draft, which the chief mechanic may edit, copy and mark
 *  as sent. The server sends nothing: «Отправить» records who sent what to whom, and when. */
function Letter({ item, onDone }: { item: ContradictionItem; onDone: (i: ContradictionItem) => void }) {
  const [to, setTo] = useState<LetterTo>('manufacturer')
  const [draft, setDraft] = useState<{ to: LetterTo; text: string; channel: string } | null>(null)
  const [text, setText] = useState('')
  const [by, setBy] = useState<string>(q.byDefault)
  const [state, setState] = useState<'idle' | 'loadFailed' | 'sending' | 'sendFailed' | 'copied'>('idle')

  useEffect(() => {
    let live = true
    getContradictionLetter(item.number, to)
      .then((l) => {
        if (!live) return
        setDraft(l)
        setText(l.text)
      })
      .catch(() => live && setState('loadFailed'))
    return () => {
      live = false
    }
  }, [item.number, to])

  // another addressee: a new draft from the server, the old one and its error go
  const pickTo = (next: LetterTo) => {
    if (next === to) return
    setDraft(null)
    setState('idle')
    setTo(next)
  }

  const send = () => {
    if (!draft) return
    setState('sending')
    sendContradiction(item.number, { to, by: by.trim() || q.byDefault, text: editedText(draft.text, text) })
      .then((i) => {
        setState('idle')
        onDone(i)
      })
      .catch(() => setState('sendFailed'))
  }
  const copyText = () => {
    navigator.clipboard?.writeText(text).then(
      () => setState('copied'),
      () => undefined,
    )
  }

  return (
    <section className="space-y-3" aria-label={q.letter}>
      <h2 className="text-[17px] font-semibold">{q.letter}</h2>
      <Choice
        label={q.letterTo}
        value={to}
        options={(['manufacturer', 'support'] as const).map((v) => ({ value: v, label: q.letterToChoice[v] }))}
        onChange={pickTo}
      />
      {draft === null && state !== 'loadFailed' && (
        <p className="text-dim" role="status">
          {q.letterLoading}
        </p>
      )}
      {state === 'loadFailed' && <p role="alert">{q.letterFailed}</p>}
      {draft && (
        <>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            aria-label={q.letter}
            className={`${FIELD} text-[15px] leading-snug`}
          />
          {draft.channel === 'none' && <p className="text-[13px] text-dim">{q.letterNone}</p>}
          <label className="block space-y-1">
            <span className="text-[13px] text-dim">{q.by}</span>
            <input value={by} onChange={(e) => setBy(e.target.value)} maxLength={120} className={`${FIELD} min-h-12`} />
          </label>
          {state === 'sendFailed' && <p role="alert">{q.sendFailed}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={copyText} className={`${BUTTON} flex-1`}>
              {state === 'copied' ? q.copied : q.copy}
            </button>
            <button type="button" onClick={send} disabled={state === 'sending'} className={`${PRIMARY} flex-1`}>
              {state === 'sending' ? q.sending : q.send}
            </button>
          </div>
        </>
      )}
    </section>
  )
}

/** The answer of the maker or of support, as the chief mechanic records it. After it the mechanics see the
 *  decision beside both wordings, not instead of them. */
function Decide({ item, onDone }: { item: ContradictionItem; onDone: (i: ContradictionItem) => void }) {
  const lastTo = item.sent?.at(-1)?.to
  const [text, setText] = useState('')
  const [source, setSource] = useState<ResolutionSource>(lastTo ?? 'manufacturer')
  const [doc, setDoc] = useState('')
  const [by, setBy] = useState<string>(q.byDefault)
  const [state, setState] = useState<'idle' | 'saving' | 'failed'>('idle')

  const save = () => {
    setState('saving')
    resolveContradiction(item.number, {
      text: text.trim(),
      by: by.trim() || q.byDefault,
      source,
      ...(doc.trim() ? { document: doc.trim() } : {}),
    })
      .then((i) => {
        setState('idle')
        onDone(i)
      })
      .catch(() => setState('failed'))
  }

  return (
    <section className="space-y-3" aria-label={q.decide}>
      <div>
        <h2 className="text-[17px] font-semibold">{q.decide}</h2>
        <p className="mt-0.5 text-[13px] text-dim">{q.decideHint}</p>
      </div>
      <label className="block space-y-1">
        <span className="text-[13px] text-dim">{q.decideText}</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          maxLength={4000}
          className={`${FIELD} text-[15px] leading-snug`}
        />
      </label>
      <div className="space-y-1">
        <span className="text-[13px] text-dim">{q.decideSource}</span>
        <Choice
          label={q.decideSource}
          value={source}
          options={(['manufacturer', 'support', 'chief_mechanic'] as const).map((v) => ({ value: v, label: q.to[v] }))}
          onChange={setSource}
        />
      </div>
      <label className="block space-y-1">
        <span className="text-[13px] text-dim">{q.decideDocument}</span>
        <input value={doc} onChange={(e) => setDoc(e.target.value)} maxLength={500} className={`${FIELD} min-h-12`} />
      </label>
      <label className="block space-y-1">
        <span className="text-[13px] text-dim">{q.by}</span>
        <input value={by} onChange={(e) => setBy(e.target.value)} maxLength={120} className={`${FIELD} min-h-12`} />
      </label>
      {state === 'failed' && <p role="alert">{q.decideFailed}</p>}
      <button
        type="button"
        onClick={save}
        disabled={state === 'saving' || text.trim() === ''}
        className={`${PRIMARY} w-full`}
      >
        {state === 'saving' ? q.sending : q.decideSave}
      </button>
    </section>
  )
}

function Item({ item, onChange }: { item: ContradictionItem; onChange: (i: ContradictionItem) => void }) {
  const res = item.status === 'resolved' ? item.resolution : null
  return (
    <div className="space-y-5 px-4 pt-3 pb-8">
      <div className="space-y-1">
        <p className={`text-[13px] ${toneOf[item.status]}`}>{q.state[item.status]}</p>
        <p className="text-[17px] font-semibold">{item.title}</p>
        <p className="text-[13px] text-dim">
          {q.engine} {item.engine} · {q.seen(item.count, plural(item.count, q.times))}
          {item.last_seen && ` · ${q.lastSeen} ${moscowTime(item.last_seen)}`}
        </p>
        {item.vehicles.length > 0 && (
          <p className="text-[13px] text-dim">
            {q.vehicles}: {item.vehicles.join(', ')}
          </p>
        )}
      </div>

      <section className="space-y-3">
        <h2 className="text-[13px] text-dim">{q.formulations}</h2>
        <ul className="space-y-3">
          {item.formulations.map((f, i) => (
            <li key={i} className="space-y-1">
              <blockquote className="border-l-2 border-line pl-3">«{f.quote}»</blockquote>
              <span className="block text-[13px] text-dim">{f.label}</span>
            </li>
          ))}
        </ul>
      </section>

      {res && (
        <section className="space-y-1 rounded-xl border border-ok/50 bg-surface px-4 py-3" aria-label={q.resolution}>
          <p className="font-semibold text-ok">{q.resolution}</p>
          <p>{res.text}</p>
          {res.document && (
            <p className="text-[13px]">
              {q.basis}: {res.document}
            </p>
          )}
          <p className="text-[13px] text-dim">
            {q.resolutionMeta(q.to[res.source] ?? res.source, moscowTime(res.at), res.by)}
          </p>
        </section>
      )}

      <section className="space-y-1">
        <h2 className="text-[13px] text-dim">{q.safeRule}</h2>
        <p>{item.safe_rule}</p>
      </section>

      {item.sent && item.sent.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[13px] text-dim">{q.sentTitle}</h2>
          <ul className="space-y-2">
            {item.sent.map((s, i) => (
              <li key={i} className="text-[13px]">
                <p>{q.sentLine(q.to[s.to] ?? s.to, moscowTime(s.at), s.by)}</p>
                <details>
                  <summary className="flex min-h-11 cursor-pointer list-none items-center text-accent [&::-webkit-details-marker]:hidden">
                    {q.showText}
                  </summary>
                  <p className="whitespace-pre-wrap text-dim">{s.text}</p>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}

      {item.status !== 'resolved' && (
        <>
          <Letter item={item} onDone={onChange} />
          <Decide key={item.status} item={item} onDone={onChange} />
        </>
      )}
    </div>
  )
}

function Journal() {
  const [events, setEvents] = useState<ContradictionEvent[] | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    getContradictionJournal()
      .then((list) => setEvents(knownEvents(list)))
      .catch(() => setFailed(true))
  }, [])
  if (failed)
    return (
      <p className="p-4" role="alert">
        {q.journalFailed}
      </p>
    )
  if (events === null)
    return (
      <p className="p-4 text-dim" role="status">
        {q.journalLoading}
      </p>
    )
  if (events.length === 0) return <p className="p-4 text-dim">{q.journalEmpty}</p>
  return (
    <>
      <p className="px-4 pt-3 pb-2 text-[13px] text-dim">{q.journalHint}</p>
      <ol className="divide-y divide-line border-y border-line">
        {events.map((e) => (
          <li key={e.seq}>
            <a href={queueHref({ view: 'item', number: e.number })} className="block px-4 py-2.5 hover:bg-surface">
              <p className="flex items-baseline justify-between gap-3">
                <span className={e.event === 'resolved' ? 'text-ok' : ''}>
                  {e.event === 'sent'
                    ? q.event.sent(e.number, q.to[e.to] ?? e.to)
                    : q.event.resolved(e.number, q.to[e.source] ?? e.source)}
                </span>
                <span className="shrink-0 text-[13px] text-mute">{e.seq}</span>
              </p>
              <p className="mt-0.5 text-[13px] text-dim">
                {moscowTime(e.at)} · {e.by}
              </p>
              {e.event === 'resolved' && (
                <p className="mt-0.5 text-[13px]">
                  {e.text}
                  {e.document && <span className="text-dim"> · {e.document}</span>}
                </p>
              )}
            </a>
          </li>
        ))}
      </ol>
    </>
  )
}

/** The chief mechanic's screen for contradictions between manuals (#93): the queue by status (open, sent,
 *  resolved), an item with both wordings, the letter, «Отправить», «Решение», and the journal of decisions.
 *  Opens in the pane where a vehicle opens: `#/contradictions`, `#/contradictions/N`, `#/contradictions/journal`. */
export function ContradictionQueue({ route, onBack }: { route: QueueRoute; onBack: () => void }) {
  const [items, setItems] = useState<ContradictionItem[] | null>(null)
  const [failed, setFailed] = useState(false)
  const load = useCallback(() => {
    getContradictions('all')
      .then((list) => {
        setItems(list)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [])
  useEffect(load, [load])
  const retry = () => {
    setFailed(false)
    load()
  }
  const replace = (next: ContradictionItem) =>
    setItems((list) => list?.map((i) => (i.number === next.number ? next : i)) ?? [next])

  const item = route.view === 'item' ? items?.find((i) => i.number === route.number) : undefined
  const title = route.view === 'item' ? q.itemTitle(route.number) : route.view === 'journal' ? q.journal : q.title
  const backLabel = route.view === 'list' ? copy.vehicle.back : q.back
  const backClass = '-ml-3 grid size-12 shrink-0 place-items-center text-dim hover:text-text'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-line">
        <div className="flex min-h-14 items-center gap-1 px-4">
          {route.view === 'list' ? (
            <button type="button" onClick={onBack} aria-label={backLabel} className={`${backClass} min-[900px]:hidden`}>
              <Chevron back />
            </button>
          ) : (
            <a href={queueHref({ view: 'list' })} aria-label={backLabel} className={backClass}>
              <Chevron back />
            </a>
          )}
          <h1 className="min-w-0 flex-1 truncate text-[17px] font-semibold">{title}</h1>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {route.view === 'journal' ? (
          <Journal />
        ) : items === null ? (
          failed ? (
            <div className="space-y-3 p-4" role="alert">
              <p>{q.loadFailed}</p>
              <button type="button" onClick={retry} className={BUTTON}>
                {copy.retry}
              </button>
            </div>
          ) : (
            <p className="p-4 text-dim" role="status">
              {q.loading}
            </p>
          )
        ) : route.view === 'list' ? (
          <List items={items} />
        ) : item ? (
          <Item key={item.number} item={item} onChange={replace} />
        ) : (
          <p className="p-4 text-dim">{q.notFound(route.number)}</p>
        )}
      </div>
    </div>
  )
}
