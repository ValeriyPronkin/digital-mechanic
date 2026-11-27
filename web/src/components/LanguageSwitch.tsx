import { useEffect, useRef, useState } from 'react'
import { getLanguages, type LanguageInfo } from '../api'
import { copy } from '../copy'
import { UI_DEFAULTS } from '../lib/defaults'
import { getLang, LANG_AUTO, LANG_EVENT, setLang } from '../lib/lang'

/** «Язык ответа» (PR #83): «Как в вопросе» or one of the server's languages, kept on this device for the
 *  next questions. A language the speech recognition does not know says that a question is said in
 *  Russian. Without the list (the server did not give it) there is nothing to choose and no switch.
 *
 *  Folded by default (`UI_DEFAULTS.languageSwitchOpen`): one quiet line with the language in use and
 *  «изменить», which opens the select and puts the focus on it. */
export function LanguageSwitch() {
  const [languages, setLanguages] = useState<LanguageInfo[] | null>(null)
  const [lang, set] = useState(getLang)
  const [open, setOpen] = useState<boolean>(UI_DEFAULTS.languageSwitchOpen)
  const select = useRef<HTMLSelectElement>(null)
  const opened = useRef(false) // opened by the mechanic: the select takes the focus
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
  useEffect(() => {
    if (open && opened.current) select.current?.focus()
  }, [open])
  if (!languages?.length) return null
  const chosen = languages.find((l) => l.lang === lang)
  if (!open)
    return (
      <p className="flex flex-wrap items-center gap-x-1 text-[13px] text-dim">
        <span>
          {copy.lang.label}: {chosen ? chosen.name : copy.lang.autoInline}
        </span>
        <span aria-hidden>·</span>
        <button
          type="button"
          aria-expanded={false}
          onClick={() => {
            opened.current = true
            setOpen(true)
          }}
          className="-mx-1 min-h-12 px-1 text-accent underline-offset-2 hover:underline"
        >
          {copy.lang.change}
        </button>
      </p>
    )
  return (
    <label className="flex flex-wrap items-center gap-x-2 text-[13px] text-dim">
      <span className="shrink-0">{copy.lang.label}:</span>
      <select
        ref={select}
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
