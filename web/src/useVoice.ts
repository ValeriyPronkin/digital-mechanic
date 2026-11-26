import { useEffect, useRef, useState } from 'react'
import { ApiError, transcribe } from './api'
import { copy } from './copy'

const MAX_MS = 30_000

/** Recording needs a secure page and a browser with MediaRecorder; where it is missing there is no button. */
export const voiceSupported =
  typeof MediaRecorder !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function'

type State = 'idle' | 'recording' | 'sending'

/** Voice input: tap, say the question, tap. The text goes to `onText` for the mechanic to check; it is
 *  never sent to the agent from here. */
export function useVoice(onText: (text: string) => void) {
  const [state, setState] = useState<State>('idle')
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const gone = useRef(false) // the screen was left: release the microphone, send nothing

  const stop = () => {
    window.clearTimeout(timer.current)
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }

  useEffect(() => {
    gone.current = false
    return () => {
      gone.current = true
      stop()
    }
  }, [])

  const start = async () => {
    setError(null)
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError(copy.thread.voice.denied)
      return
    }
    const rec = new MediaRecorder(stream)
    const chunks: Blob[] = []
    rec.ondataavailable = (e) => chunks.push(e.data)
    rec.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      if (gone.current) return
      setState('sending')
      try {
        const { text } = await transcribe(new Blob(chunks, { type: rec.mimeType }))
        if (!gone.current) onText(text)
      } catch (e) {
        setError(e instanceof ApiError && e.detail ? e.detail : copy.thread.voice.failed)
      } finally {
        setState('idle')
      }
    }
    recorder.current = rec
    rec.start()
    setState('recording')
    timer.current = window.setTimeout(stop, MAX_MS)
  }

  const toggle = () => {
    if (state === 'recording') stop()
    else if (state === 'idle') void start()
  }

  return { state, error, toggle, clearError: () => setError(null) }
}
