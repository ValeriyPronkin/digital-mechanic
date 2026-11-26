import assert from 'node:assert/strict'
import { test } from 'node:test'
import { LEVEL_KEY, getLevel, setLevel } from '../src/lib/level.ts'

const memory = () => {
  const data = new Map<string, string>()
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) }
}

test('the level is kept on the device, «По шагам» until the mechanic chooses', () => {
  const store = memory()
  assert.equal(getLevel(store), 'steps')
  setLevel('expert', store)
  assert.equal(getLevel(store), 'expert')
  store.setItem(LEVEL_KEY, 'short') // the first page stored «short» for «expert»
  assert.equal(getLevel(store), 'expert')
  store.setItem(LEVEL_KEY, 'boss')
  assert.equal(getLevel(store), 'steps')
})

test('the first-visit question is asked until the mechanic answers it', async () => {
  const { isLevelChosen } = await import('../src/lib/level.ts')
  const store = memory()
  assert.equal(isLevelChosen(store), false)
  setLevel('steps', store)
  assert.equal(isLevelChosen(store), true)
})
