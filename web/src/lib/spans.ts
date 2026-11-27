// Parts and tools in the answer, each in its own colour (docs/api-v2-web.md §8, PR #163). The server marks
// them by the registry of the manuals; the screen only finds the marked words in what it draws.
// Tested in web/tests/spans.test.ts.
import type { AnswerSpan } from '../api.ts'

/** A piece of a drawn line: plain text, or a marked part or tool. */
export type Piece = { text: string; span?: AnswerSpan }

const KINDS = new Set(['part', 'tool'])

/** The spans the screen can draw: a known kind and a non-empty piece of text. A new kind may come before the
 *  screen learns it, and it is left as plain text. */
export function usableSpans(spans: readonly AnswerSpan[] | undefined): AnswerSpan[] {
  return (spans ?? []).filter((s) => KINDS.has(s.type) && typeof s.text === 'string' && s.text.trim() !== '')
}

/** Marks the spans in the text pieces of an answer, in the order they are drawn.
 *
 *  `start`/`end` count in the text of the `text` event; what is drawn is that text cut into paragraphs, list
 *  items and chips, with `**` taken out, and after `verification` the checked text replaces it. So each span
 *  is found by its own words (`span.text`), as the contract allows: the spans come in order, and each one is
 *  looked for after the one before it. A span that is not in the drawn text (its claim was withdrawn, say) is
 *  passed over, and the ones after it are still found. */
export function markPieces(texts: readonly string[], spans: readonly AnswerSpan[] | undefined): Piece[][] {
  const list = usableSpans(spans)
  let next = 0
  return texts.map((text, i) => {
    const later = texts.slice(i + 1).join('\n')
    const pieces: Piece[] = []
    let pos = 0
    while (next < list.length) {
      // the first span, in order, that is in the rest of this piece; a span before it is passed over only
      // when its words are nowhere further on, so a chance match of a later span does not skip ahead
      const rest = `${text.slice(pos)}\n${later}`
      let at = -1
      let j = next
      for (; j < list.length; j++) {
        at = text.indexOf(list[j].text, pos)
        if (at >= 0 || rest.includes(list[j].text)) break
      }
      if (at < 0) break
      if (at > pos) pieces.push({ text: text.slice(pos, at) })
      pieces.push({ text: list[j].text, span: list[j] })
      pos = at + list[j].text.length
      next = j + 1
    }
    if (pos < text.length || pieces.length === 0) pieces.push({ text: text.slice(pos) })
    return pieces
  })
}

/** The hint under a marked word: its designation and its page, as the server sent them. */
export function spanHint(s: AnswerSpan): { designation: string | null; page: number | null } {
  return { designation: s.designation?.trim() || null, page: s.page ?? null }
}
