/** The language of the answer the mechanic chose (PR #83). Kept on the device, like the level. «Как в
 *  вопросе» (`auto`) leaves it to the server: the answer comes in the language of the question, and a
 *  question is said in Russian. A chosen language is sent with every question and is the language a
 *  spoken question is recognized in; where recognition does not know it (tg, ky, hi) the server takes
 *  Russian. */
export const LANG_KEY = 'dm-lang'
export const LANG_AUTO = 'auto'
export const LANG_EVENT = 'dm-lang'

type Store = Pick<Storage, 'getItem' | 'setItem'>

const storage = (): Store | null => (typeof localStorage === 'undefined' ? null : localStorage)

/** A language code as the server writes them: «uz», «uz-cyrl». Anything else reads as «Как в вопросе». */
const CODE = /^[a-z]{2}(-[a-z]{4})?$/

export function getLang(store: Store | null = storage()): string {
  const v = store?.getItem(LANG_KEY)
  return v && CODE.test(v) ? v : LANG_AUTO
}

export function setLang(code: string, store: Store | null = storage()): void {
  store?.setItem(LANG_KEY, CODE.test(code) ? code : LANG_AUTO)
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(LANG_EVENT))
}

/** `lang` of /api/v2/chat: left out for «Как в вопросе». */
export const chatLang = (code: string): string | undefined => (code === LANG_AUTO ? undefined : code)

/** `lang` of /api/v2/transcribe: the chosen language, Russian for «Как в вопросе». */
export const voiceLang = (code: string): string => (code === LANG_AUTO ? 'ru' : code)

/** «Показать по-русски» is offered under an answer that was given in another language and has its
 *  Russian version (SSE `back_translation`; `back_translation` of a restored turn). */
export const offersRussian = (turn: { back_translation?: string | null; language?: { lang: string } }) =>
  !!turn.back_translation && turn.language?.lang !== 'ru'
