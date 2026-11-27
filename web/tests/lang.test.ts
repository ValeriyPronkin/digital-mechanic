// The language of the answer the mechanic chose, and «Показать по-русски» (PR #83, #86). Run with `npm test`.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chatLang, getLang, LANG_AUTO, LANG_KEY, offersRussian, setLang, voiceLang } from '../src/lib/lang.ts'
import { speechRequest } from '../src/lib/speech.ts'

const memory = () => {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }
}

test('nothing chosen: the answer comes in the language of the question, and a question is said in Russian', () => {
  const store = memory()
  assert.equal(getLang(store), LANG_AUTO)
  assert.equal(chatLang(getLang(store)), undefined)
  assert.equal(voiceLang(getLang(store)), 'ru')
})

test('a chosen language goes with every question and is the language a spoken question is heard in', () => {
  const store = memory()
  setLang('uz-cyrl', store)
  assert.equal(getLang(store), 'uz-cyrl')
  assert.equal(chatLang(getLang(store)), 'uz-cyrl')
  assert.equal(voiceLang(getLang(store)), 'uz-cyrl')
})

test('a value that is not a language code reads as «Как в вопросе»', () => {
  const store = memory()
  store.setItem(LANG_KEY, '../../etc')
  assert.equal(getLang(store), LANG_AUTO)
  setLang('<script>', store)
  assert.equal(getLang(store), LANG_AUTO)
})

test('«Показать по-русски» only under an answer in another language that has its Russian version', () => {
  assert.equal(offersRussian({ back_translation: 'Зазор 0,25 мм [R1].', language: { lang: 'uz' } }), true)
  assert.equal(offersRussian({ back_translation: 'Зазор 0,25 мм [R1].' }), true) // a restored turn
  assert.equal(offersRussian({ back_translation: null, language: { lang: 'uz' } }), false)
  assert.equal(offersRussian({ back_translation: 'Зазор', language: { lang: 'ru' } }), false)
})

test('the voice is asked for in the language of the answer when the server names it', () => {
  const sig = 'a'.repeat(64)
  const [, init] = speechRequest({ text: 'Zazor 0,25 mm.', sig, url: '/api/voice/speak', lang: 'uz' })
  assert.deepEqual(JSON.parse(String(init.body)), { text: 'Zazor 0,25 mm.', sig, lang: 'uz' })
  const [, ru] = speechRequest({ text: 'Зазор 0,25 мм.', sig, url: '/api/voice/speak' })
  assert.deepEqual(JSON.parse(String(ru.body)), { text: 'Зазор 0,25 мм.', sig })
})
