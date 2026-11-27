// The theme of the screen: what is stored, what is drawn. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readChoice, resolve } from '../src/lib/theme.ts'

test('a stored choice is read back; nothing or an unknown value is the dark theme, as before', () => {
  assert.equal(readChoice('light'), 'light')
  assert.equal(readChoice('system'), 'system')
  assert.equal(readChoice('dark'), 'dark')
  assert.equal(readChoice(null), 'dark')
  assert.equal(readChoice('blue'), 'dark')
})

test('«Как в системе» follows the system; a fixed choice does not', () => {
  assert.equal(resolve('system', true), 'light')
  assert.equal(resolve('system', false), 'dark')
  assert.equal(resolve('light', false), 'light')
  assert.equal(resolve('dark', true), 'dark')
})
