import { useEffect, useRef, useState } from 'react'
import { ApiError, transcribe } from './api'
import { copy } from './copy'
import { toWav16k } from './lib/wav'

const MAX_MS = 30_000

type Ctx = typeof AudioContext

/** Recording needs a secure page, the microphone and WebAudio; where they are missing there is no button.
 *  Our server recognizes WAV PCM 16 kHz mono (issue #52): the recording is taken through WebAudio, not
 *  MediaRecorder, whose webm/mp4 our speech recognition does not accept. */
export const voiceSupported =
  typeof navigator !== 'undefined' &&
  typeof navigator.mediaDevices?.getUserMedia === 'function' &&
  typeof window !== 'undefined' &&
  ('AudioContext' in window || 'webkitAudioContext' in window)

type State = 'idle' | 'recording' | 'sending'

/** Voice input: tap, say the question, tap. The text goes to `onText` for the mechanic to check; it is
 *  never sent to the agent from here. */
export function useVoice(onText: (text: string) => void) {
  const [state, setState] = useState<State>('idle')
  const [error, setError] = useState<string | null>(null)
  const rec = useRef<{
    ctx: AudioContext
    stream: MediaStream
    node: ScriptProcessorNode
    chunks: Float32Array[]
  } | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const gone = useRef(false) // the screen was left: release the microphone, send nothing

  const release = () => {
    const r = rec.current
    rec.current = null
    if (!r) return null
    r.node.disconnect()
    r.node.onaudioprocess = null
    r.stream.getTracks().forEach((track) => track.stop())
    void r.ctx.close().catch(() => undefined)
    return r
  }

  const stop = async () => {
    window.clearTimeout(timer.current)
    const r = release()
    if (!r || gone.current) return
    setState('sending')
    try {
      const wav = new Blob([toWav16k(r.chunks, r.ctx.sampleRate)], { type: 'audio/wav' })
      const { text } = await transcribe(wav)
      if (!gone.current) onText(text)
    } catch (e) {
      setError(e instanceof ApiError && e.detail ? e.detail : copy.thread.voice.failed)
    } finally {
      setState('idle')
    }
  }

  useEffect(() => {
    gone.current = false
    return () => {
      gone.current = true
      window.clearTimeout(timer.current)
      release()
    }
  }, [])

  const start = async () => {
    setError(null)
    // The context is made in the tap itself: an iPhone keeps a context made later suspended.
    const AC: Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: Ctx }).webkitAudioContext
    const ctx = new AC()
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch {
      void ctx.close()
      setError(copy.thread.voice.denied)
      return
    }
    await ctx.resume().catch(() => undefined)
    const node = ctx.createScriptProcessor(4096, 1, 1)
    const chunks: Float32Array[] = []
    node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
    ctx.createMediaStreamSource(stream).connect(node)
    node.connect(ctx.destination)
    rec.current = { ctx, stream, node, chunks }
    setState('recording')
    timer.current = window.setTimeout(() => void stop(), MAX_MS)
  }

  const toggle = () => {
    if (state === 'recording') void stop()
    else if (state === 'idle') void start()
  }

  return { state, error, toggle, clearError: () => setError(null) }
}
