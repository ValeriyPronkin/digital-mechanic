// The compact answer: a short lead, the rest under «Весь ответ», small numbered marks in the text instead of
// chips, and one list of the manual's pages under it — each page once, by document. The server's text is
// not changed: this is only how it is drawn. Tested in web/tests/footnotes.test.ts.
import type { SourceItem } from '../api.ts'
import type { Inline, Node } from './answer.ts'

type Sources = Record<string, SourceItem>

/** One page of a manual, numbered by where the answer first cites it. Several handles may name it. */
export interface CitedPage {
  n: number
  source: SourceItem // the first handle that names this page: the list opens the page by it
  handles: string[]
}
/** The pages of one document, in the order the answer first cites them. */
export interface CitedDoc {
  manual_id: string
  pages: CitedPage[]
}
export interface Footnotes {
  numberOf: Map<string, number> // handle → number of its page
  docs: CitedDoc[]
}

const key = (s: SourceItem) => `${s.manual_id}\u0000${s.pdf_page}`

/** The handles of the chips, in the order they are drawn; the pages of withdrawn claims are not here: the
 *  withdrawal note shows them itself. */
export function citedHandles(nodes: readonly Node[]): string[] {
  const lines = nodes.flatMap((n): Inline[][] =>
    n.kind === 'section' ? [] : n.kind === 'paragraph' ? [n.inline] : n.items,
  )
  return lines.flat().flatMap((p) => (p.kind === 'source' ? [p.handle] : []))
}

/** Numbers each page of the manuals once, by its first citation, and groups the pages by document. A handle
 *  the server never issued gets no number and no page, as it gets no chip. */
export function footnotes(handles: readonly string[], sources: Sources): Footnotes {
  const numberOf = new Map<string, number>()
  const byKey = new Map<string, CitedPage>()
  const docs: CitedDoc[] = []
  for (const handle of handles) {
    const s = sources[handle]
    if (!s || numberOf.has(handle)) continue
    let page = byKey.get(key(s))
    if (!page) {
      page = { n: byKey.size + 1, source: s, handles: [] }
      byKey.set(key(s), page)
      let doc = docs.find((d) => d.manual_id === s.manual_id)
      if (!doc) docs.push((doc = { manual_id: s.manual_id, pages: [] }))
      doc.pages.push(page)
    }
    page.handles.push(handle)
    numberOf.set(handle, page.n)
  }
  return { numberOf, docs }
}

const SOURCES = 'источники' // the section of that name in copy.sections

/** The answer's own «Источники» section is the list of pages again: the list under the answer takes its
 *  place. Everything up to the next section goes with it; its handles are still counted (they are cited). */
export function withoutSources(nodes: readonly Node[]): Node[] {
  const out: Node[] = []
  let skip = false
  for (const n of nodes) {
    if (n.kind === 'section') skip = n.title.toLowerCase() === SOURCES
    if (!skip) out.push(n)
  }
  return out
}

/** «Коротко»: the first paragraph, which the server puts first (the answer itself); the rest goes under
 *  «Весь ответ». An answer of one block, or one that starts with a section title or a list, is not split. */
export function splitLead(nodes: readonly Node[]): { lead: Node | null; rest: Node[] } {
  const [first, ...rest] = nodes
  if (first?.kind !== 'paragraph' || rest.length === 0) return { lead: null, rest: [...nodes] }
  return { lead: first, rest }
}
