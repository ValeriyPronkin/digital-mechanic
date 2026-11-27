import { useEffect, useState } from 'react'
import { getBuild } from '../api'
import { versionLine } from '../lib/version'

/** «версия 2ce108f · 27.11 13:30» at the end of the fleet list (docs/api-v2-web.md §7): the jury can check
 *  which build it sees against main. Asked once; no answer reads «версия неизвестна». The full commit is in
 *  the tooltip, to copy. */
export function VersionFooter() {
  const [line, setLine] = useState<string | null>(null)
  const [sha, setSha] = useState<string | undefined>()
  useEffect(() => {
    let live = true
    getBuild()
      .then((b) => {
        if (!live) return
        setLine(versionLine(b))
        setSha(b?.git_sha)
      })
      .catch(() => live && setLine(versionLine(null)))
    return () => {
      live = false
    }
  }, [])
  if (line === null) return null
  return (
    <p className="px-4 pt-4 pb-6 text-[12px] text-mute" title={sha}>
      {line}
    </p>
  )
}
