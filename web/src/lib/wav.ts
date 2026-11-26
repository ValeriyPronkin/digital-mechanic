/** WAV PCM 16 kHz mono from WebAudio samples: what our speech recognition (SpeechKit) accepts.
 *  MediaRecorder gives webm/opus in Chrome and mp4/aac on an iPhone, which it does not (issue #14). */
export const WAV_RATE = 16000

export function toWav16k(chunks: Float32Array[], rate: number): ArrayBuffer {
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const all = new Float32Array(total)
  let offset = 0
  for (const c of chunks) {
    all.set(c, offset)
    offset += c.length
  }
  const ratio = rate / WAV_RATE
  const n = Math.floor(total / ratio)
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const str = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i))
  }
  str(0, 'RIFF')
  v.setUint32(4, 36 + n * 2, true)
  str(8, 'WAVE')
  str(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, WAV_RATE, true)
  v.setUint32(28, WAV_RATE * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  str(36, 'data')
  v.setUint32(40, n * 2, true)
  for (let i = 0; i < n; i++) {
    // the mean of the window is a simple low-pass before taking every ratio-th sample
    const a = Math.floor(i * ratio)
    const b = Math.min(total, Math.floor((i + 1) * ratio))
    let s = 0
    for (let j = a; j < b; j++) s += all[j]
    const x = Math.max(-1, Math.min(1, s / Math.max(1, b - a)))
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true)
  }
  return buf
}
