import { useEffect, useRef, useState } from 'react'
import type { SpeechInfo } from '../api'
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
        setError('Нажмите ещё раз, чтобы прослушать.')
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
        throw new Error(typeof body?.detail === 'string' ? body.detail : 'Озвучка недоступна — ответ на экране.')
      }
      url.current = URL.createObjectURL(await res.blob())
      play(url.current)
    } catch (e) {
      setState('idle')
      setError(e instanceof Error ? e.message : 'Озвучка недоступна — ответ на экране.')
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
        aria-label={state === 'playing' ? 'Остановить озвучку' : 'Прослушать короткий ответ'}
        className="min-h-12 rounded-lg border border-line px-3 text-[13px] text-text disabled:opacity-50"
      >
        {state === 'playing' ? '■ Стоп' : state === 'loading' ? 'Готовлю звук…' : '▶ Прослушать'}
      </button>
      {error && <span className="text-[13px] text-warn">{error}</span>}
    </div>
  )
}
