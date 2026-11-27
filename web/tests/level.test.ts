import assert from 'node:assert/strict'
import { test } from 'node:test'
import { levelOf, moreDetail, redoLevel, shorter } from '../src/lib/level.ts'

test('the level of an answer is read as the server writes it, the first two-level names too', () => {
  assert.equal(levelOf('novice'), 'novice')
  assert.equal(levelOf('mechanic'), 'mechanic')
  assert.equal(levelOf('master'), 'master')
  assert.equal(levelOf('steps'), 'novice') // «Пошагово» (#17)
  assert.equal(levelOf('expert'), 'master') // «Опытный» (#17)
  assert.equal(levelOf('auto'), null)
  assert.equal(levelOf(null), null)
  assert.equal(levelOf(undefined), null)
})

test('«Подробнее» is a level down, «Короче» a level up, and neither goes past the end', () => {
  assert.equal(moreDetail('master'), 'mechanic')
  assert.equal(moreDetail('mechanic'), 'novice')
  assert.equal(moreDetail('novice'), null)
  assert.equal(shorter('novice'), 'mechanic')
  assert.equal(shorter('mechanic'), 'master')
  assert.equal(shorter('master'), null)
})

test('«подробнее» and «короче» — typed or said — move from the level of the last answer', () => {
  assert.equal(redoLevel('Подробнее, пожалуйста', 'master'), 'mechanic')
  assert.equal(redoLevel('по шагам', 'mechanic'), 'novice')
  assert.equal(redoLevel('Короче', 'novice'), 'mechanic')
  assert.equal(redoLevel('покороче можно?', 'mechanic'), 'master')
  assert.equal(redoLevel('подробнее', null), 'novice')
  assert.equal(redoLevel('короче', null), 'master')
  assert.equal(redoLevel('Какой зазор клапанов?', 'mechanic'), null) // the server picks
})
