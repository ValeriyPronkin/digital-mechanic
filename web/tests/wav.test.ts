import assert from 'node:assert/strict'
import { test } from 'node:test'
import { WAV_RATE, toWav16k } from '../src/lib/wav.ts'

test('48 kHz WebAudio samples become WAV PCM 16 kHz mono of the same length', () => {
  const rate = 48000
  const chunks = Array.from({ length: 3 }, (_, c) =>
    Float32Array.from({ length: 4800 }, (_, i) => 0.3 * Math.sin((2 * Math.PI * 220 * (c * 4800 + i)) / rate)),
  )
  const v = new DataView(toWav16k(chunks, rate))
  const tag = (at: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => v.getUint8(at + i)))
  assert.equal(tag(0), 'RIFF')
  assert.equal(tag(8), 'WAVE')
  assert.equal(v.getUint16(22, true), 1) // mono
  assert.equal(v.getUint32(24, true), WAV_RATE)
  assert.equal(v.getUint16(34, true), 16) // bits
  assert.equal(v.getUint32(40, true), 4800 * 2) // 0.3 s at 16 kHz, 2 bytes a sample
})
