import type { SpeechInfo } from '../api.ts'

/** The request for the spoken version: only the text the server built and signed is synthesized, in the
 *  language the server named for it (PR #83). */
export function speechRequest(sp: SpeechInfo): [string, RequestInit] {
  return [
    sp.url,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: sp.text, sig: sp.sig, ...(sp.lang ? { lang: sp.lang } : {}) }),
      credentials: 'same-origin',
    },
  ]
}

/** A silent WAV played in the tap itself: an iPhone plays sound later only on an element started by a tap. */
export const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA='
