import { useEffect, useRef, useState } from 'react'
import type { SpeechInfo } from '../api'
import { copy } from '../copy'
import { SILENT_WAV, speechRequest } from '../lib/speech'

// One player for the screen: a new answer read aloud stops the one before.
let player: HTMLAudioElement | null = null
const audio = () => (player ??= new Audio())

type State = 'idle' | 'loading' | 'playing'

/** «Прослушать»: the short spoken version of the answer (value, document and page) — for a mechanic whose hands
 *  are busy (#14). The sound is fetched once per answer and replayed from memory. */
export function SpeakButton({ speech }: { speech: SpeechInfo }) {
  const [state, setState] = useState<State>('idle')
  const [error, setError] = useState<string | null>(null)
  const url = useRef<string | null>(null)

  useEffect(
    () => () => {
      if (url.current) URL.revokeObjectURL(url.current)
    },
    [],
  )

  const play = (src: string) => {
    const a = audio()
    a.src = src
    a.onended = () => setState('idle')
    a.play()
      .then(() => setState('playing'))
      .catch(() => {
        setState('idle')
        setError(copy.speech.again)
      })
  }

  const start = async () => {
    setError(null)
    const a = audio()
    if (url.current) return play(url.current)
    a.src = SILENT_WAV // unlock the element in the tap itself: the sound comes after the request
    void a.play().catch(() => undefined)
    setState('loading')
    try {
      const res = await fetch(...speechRequest(speech))
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : copy.speech.unavailable)
      }
      url.current = URL.createObjectURL(await res.blob())
      play(url.current)
    } catch (e) {
      setState('idle')
      setError(e instanceof Error ? e.message : copy.speech.unavailable)
    }
  }

  const stop = () => {
    audio().pause()
    setState('idle')
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={state === 'playing' ? stop : () => void start()}
        disabled={state === 'loading'}
        aria-label={state === 'playing' ? copy.speech.stopLabel : copy.speech.playLabel}
        className="inline-flex min-h-12 items-center gap-2 rounded-lg border border-line px-3 text-[13px] text-text disabled:opacity-50"
      >
        {/* drawn, not typed: iOS shows ▶ and ■ as colour emoji */}
        {state === 'playing' ? (
          <>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden>
              <rect x="2" y="2" width="8" height="8" rx="1" />
            </svg>
            {copy.speech.stop}
          </>
        ) : state === 'loading' ? (
          copy.speech.loading
        ) : (
          <>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden>
              <path d="M3 1.8v8.4a.5.5 0 0 0 .76.43l6.9-4.2a.5.5 0 0 0 0-.86l-6.9-4.2A.5.5 0 0 0 3 1.8z" />
            </svg>
            {copy.speech.play}
          </>
        )}
      </button>
      {error && <span className="text-[13px] text-warn">{error}</span>}
    </div>
  )
}
