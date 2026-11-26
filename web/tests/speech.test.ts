import assert from 'node:assert/strict'
import { test } from 'node:test'
import { speechRequest } from '../src/lib/speech.ts'

test('only the signed text the server built goes to synthesis', () => {
  const [url, init] = speechRequest({ text: 'Зазор 0,25–0,30 мм.', sig: 'a'.repeat(64), url: '/api/voice/speak' })
  assert.equal(url, '/api/voice/speak')
  assert.equal(init.method, 'POST')
  assert.deepEqual(JSON.parse(String(init.body)), { text: 'Зазор 0,25–0,30 мм.', sig: 'a'.repeat(64) })
})
