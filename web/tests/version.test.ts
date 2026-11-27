// The version in the footer (docs/api-v2-web.md §7). Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { versionLine } from '../src/lib/version.ts'

test('the commit and the build time by Moscow time', () => {
  assert.equal(
    versionLine({ git_sha_short: '2ce108f', built_at: '2026-11-27T10:30:00Z', source: 'image' }),
    'версия 2ce108f · 27.11 13:30',
  )
})

test('no build time (a local copy): the commit alone', () => {
  assert.equal(versionLine({ git_sha_short: '2ce108f', built_at: null, source: 'git' }), 'версия 2ce108f')
  assert.equal(versionLine({ git_sha_short: '2ce108f', built_at: 'не время', source: 'git' }), 'версия 2ce108f')
})

test('unknown, absent or no answer: «версия неизвестна»', () => {
  assert.equal(versionLine({ git_sha_short: 'unknown', built_at: null, source: 'unknown' }), 'версия неизвестна')
  assert.equal(versionLine({ git_sha_short: '2ce108f', source: 'unknown' }), 'версия неизвестна')
  assert.equal(versionLine(null), 'версия неизвестна')
  assert.equal(versionLine({}), 'версия неизвестна')
})
