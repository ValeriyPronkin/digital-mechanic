import { useEffect, useState } from 'react'
import { getLanguages, type LanguageInfo } from '../api'
import { copy } from '../copy'
import { getLang, LANG_AUTO, LANG_EVENT, setLang } from '../lib/lang'

/** «Язык ответа» (PR #83): «Как в вопросе» or one of the server's languages, kept on this device for the
 *  next questions. A language the speech recognition does not know says that a question is said in
 *  Russian. Without the list (the server did not give it) there is nothing to choose and no switch. */
export function LanguageSwitch() {
  const [languages, setLanguages] = useState<LanguageInfo[] | null>(null)
  const [lang, set] = useState(getLang)
  useEffect(() => {
    let stale = false
    getLanguages()
      .then((list) => !stale && setLanguages(list))
      .catch(() => undefined)
    const follow = () => set(getLang())
    window.addEventListener(LANG_EVENT, follow)
    return () => {
      stale = true
      window.removeEventListener(LANG_EVENT, follow)
    }
  }, [])
  if (!languages?.length) return null
  const chosen = languages.find((l) => l.lang === lang)
  return (
    <label className="flex flex-wrap items-center gap-x-2 text-[13px] text-dim">
      <span className="shrink-0">{copy.lang.label}:</span>
      <select
        value={chosen ? lang : LANG_AUTO}
        onChange={(e) => {
          setLang(e.target.value)
          set(e.target.value)
        }}
        // 16 px: a smaller select makes an iPhone zoom the page in
        className="min-h-12 min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-2 text-[16px] text-text min-[900px]:max-w-64 min-[900px]:flex-none"
      >
        <option value={LANG_AUTO}>{copy.lang.auto}</option>
        {languages.map((l) => (
          <option key={l.lang} value={l.lang}>
            {l.name}
          </option>
        ))}
      </select>
      {chosen && !chosen.voice_input && <span>{copy.lang.voiceRu}</span>}
    </label>
  )
}
