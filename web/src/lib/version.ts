// The version in the footer (docs/api-v2-web.md §7): which build the jury looks at, checked against main.
// Tested in web/tests/version.test.ts.
import { copy } from '../copy.ts'

export interface BuildInfo {
  git_sha?: string
  git_sha_short?: string
  built_at?: string | null
  source?: 'image' | 'git' | 'unknown' | string
}

const MSK = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/** «27.11 13:30» by Moscow time: the server writes UTC. Null for what is not a time. */
export function moscowShort(iso: string): string | null {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const p = Object.fromEntries(MSK.formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.day}.${p.month} ${p.hour}:${p.minute}`
}

/** «версия 2ce108f · 27.11 13:30»; without the time of the build, the commit alone; «версия неизвестна»
 *  when the server does not know it (`source: unknown`) or did not answer. */
export function versionLine(build: BuildInfo | null | undefined): string {
  const sha = build?.git_sha_short
  if (!build || build.source === 'unknown' || !sha || sha === 'unknown') return copy.version.unknown
  const at = build.built_at ? moscowShort(build.built_at) : null
  return at ? copy.version.line(sha, at) : copy.version.line(sha)
}
