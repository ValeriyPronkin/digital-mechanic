// The page of each work and part of a ticket (web/tests/sheet.test.ts): on the ticket sheet before it is sent,
// on the card of a sent ticket, and on its printed sheet. Ported from Nikita's interface (lib/sheet.ts).
import type { SourceItem, TicketItem, TicketLine } from '../api.ts'
import { pageLabel, sourceLabel } from './format.ts'

/** A page of a manual the ticket cites: the `references` of the body sent to ТОиР. */
export interface Reference {
  manual: string
  pdf_page: number
}

/** A work or a part as the card and the printed sheet show it. `page` is «ЯМЗ-236… Руководство по ремонту,
 *  стр. 269» in words, or null when the ticket does not say which of its pages the line is on. */
export interface SheetLine {
  text: string
  page: string | null
  scanned: boolean
  /** The same page as one the screen can open: there when the record names the manual by its id. */
  source?: SourceItem
}

/** What a sent ticket shows of its works, parts and pages. */
export interface SheetLines {
  works: SheetLine[]
  parts: SheetLine[]
  /** The pages listed once under the works: only when some line does not carry its own page. */
  pages: string[]
}

/** A line's page as the page viewer opens it, and as a chip names it. Null when the server did not know
 *  the page (a part the model named that is not in the manual's list) or the line is older than pages. */
export function lineSource(line: {
  source?: string
  manual_id?: string | null
  manual?: string | null
  short?: string | null
  pdf_page?: number | null
}): SourceItem | null {
  if (!line.manual_id || !line.manual || !line.pdf_page) return null
  const short = line.short || line.manual
  return {
    handle: line.source ?? '',
    manual_id: line.manual_id,
    short,
    chip: short,
    designation: line.manual,
    pdf_page: line.pdf_page,
  }
}

/** The chip of a work or a part on the ticket sheet: the thread's source when the handle is one the answer
 *  cited, else the page the server put on the line (a page of the manual's matrix the answer did not cite). */
export function itemSource(item: TicketItem, sources: Record<string, SourceItem>): SourceItem | undefined {
  return (item.source ? sources[item.source] : undefined) ?? lineSource(item) ?? undefined
}

/** The works with the page each is on, for a ticket that does not keep its lines.
 *
 *  The body sent to ТОиР has the works as text and the pages as one list for the whole ticket. So a work's
 *  own page is known only when the ticket cites a single page: then every work is on it. With several pages
 *  the works go without a page and the pages are listed once under them (`pagesByManual`). */
export function worksWithPages(operations: readonly string[], references: readonly Reference[]): SheetLine[] {
  const only =
    references.length === 1 ? sourceLabel({ short: references[0].manual, pdf_page: references[0].pdf_page }) : null
  return operations.map((text) => ({ text, page: only, scanned: false }))
}

/** The pages of the ticket in words, one entry per manual, in the order the ticket has them. */
export function pagesByManual(references: readonly Reference[]): string[] {
  const pages = new Map<string, number[]>()
  for (const r of references) {
    const list = pages.get(r.manual) ?? []
    if (!list.includes(r.pdf_page)) list.push(r.pdf_page)
    pages.set(r.manual, list)
  }
  return [...pages.entries()].map(([manual, list]) => `${manual}, ${pageLabel(list.join(', '))}`)
}

const same = (texts: readonly string[], lines: readonly TicketLine[]) =>
  texts.length === lines.length && texts.every((text, i) => text === lines[i].text)

/** The works, the parts and the pages of a sent ticket.
 *
 *  A ticket that keeps its lines (`TicketView.lines`) shows every work and part with its own page. A ticket
 *  stored before that has only the payload: `worksWithPages`, the parts as text, the pages listed once.
 *
 *  What is shown is what was sent: the lines are used only when they are the payload's works and parts,
 *  text for text and in order. A record that disagrees with the payload is not trusted with the pages. */
export function sheetLines(
  payload: { operations: readonly string[]; spare_parts: readonly string[]; references: readonly Reference[] },
  lines?: { operations: readonly TicketLine[]; spare_parts: readonly TicketLine[] } | null,
): SheetLines {
  if (lines && same(payload.operations, lines.operations) && same(payload.spare_parts, lines.spare_parts)) {
    const withPage = (line: TicketLine): SheetLine => {
      const source = lineSource(line)
      return {
        text: line.text,
        // the manual by its short name, as on a chip: «РК ЯМЗ-236М2, стр. 269» keeps a work and its page on one line
        page:
          line.manual && line.pdf_page
            ? sourceLabel({ short: line.short || line.manual, pdf_page: line.pdf_page })
            : null,
        scanned: line.scanned,
        ...(source ? { source } : {}),
      }
    }
    const works = lines.operations.map(withPage)
    const parts = lines.spare_parts.map(withPage)
    // a work without its page: the ticket's pages once under the works, so none of them is lost
    const pages = works.every((w) => w.page) ? [] : pagesByManual(payload.references)
    return { works, parts, pages }
  }
  const works = worksWithPages(payload.operations, payload.references)
  return {
    works,
    parts: payload.spare_parts.map((text) => ({ text, page: null, scanned: false })),
    pages: works.some((w) => w.page) ? [] : pagesByManual(payload.references),
  }
}

/** The conclusion cut after its first word when that word is the verdict: «Вероятно», «Предварительно».
 *  The printed sheet sets the word in bold, so a preliminary result is seen as one before the sentence is
 *  read. A conclusion that does not start so comes back whole, with no word to mark. */
export function verdictWord(conclusion: string): [word: string, rest: string] {
  const m = conclusion.match(/^(\p{Lu}\p{Ll}+):\s+(.*)$/su)
  return m ? [m[1], m[2]] : ['', conclusion]
}
