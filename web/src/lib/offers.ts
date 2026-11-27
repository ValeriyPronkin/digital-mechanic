// What the ticket sheet shows of the suppliers' offers for the parts of a draft. Named in full: web/tests
// load this module in Node.
import type { PartOffer, PartOffersItem, PartsOffers } from '../api.ts'
import { copy } from '../copy.ts'

const NBSP = ' '

/** The offers of the parts still in the ticket, or null when there is not one offer to show: no parts in the
 *  draft, a draft saved before the field existed, every part removed by the mechanic, no supplier connected
 *  (the stand has none: «Каталог поставщика не подключён» is a fact about the setup, not about the part, and
 *  the sheet says nothing about it), or no supplier has any of the parts. A part no supplier has stays in a
 *  list where another part has an offer: its note says so. */
export function shownOffers(
  offers: PartsOffers | null | undefined,
  removed: Set<number>,
): { note: string; items: PartOffersItem[] } | null {
  if (!offers?.connected) return null
  const items = offers.items.filter((i) => !removed.has(i.index))
  if (!items.some((i) => i.offers.length > 0)) return null
  return { note: offers.note, items }
}

/** 1 250 ₽, 99,50 ₽; null without a price. */
export function priceRub(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) return null
  const whole = Number.isInteger(value)
  const text = value.toLocaleString('ru-RU', {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  })
  return `${text.replace(/\s/g, NBSP)}${NBSP}₽`
}

/** The facts of an offer in one line: designation, availability, price, lead time. */
export function offerFacts(o: PartOffer): string[] {
  const price = priceRub(o.price_rub)
  return [
    o.designation,
    o.available,
    price,
    o.lead_days === null || o.lead_days === undefined ? null : copy.ticket.offerLead(o.lead_days),
  ].filter((x): x is string => !!x)
}

/** The colour of the availability: in stock, not in stock, not said. */
export const stockTone = (inStock: boolean | null) =>
  inStock === true ? 'text-ok' : inStock === false ? 'text-warn' : 'text-dim'

/** A supplier's link is followed only when it is a web address: the URL comes from a supplier's file. */
export const webUrl = (url: string | null) => (url && /^https?:\/\//i.test(url) ? url : null)

/** «Демо-API: не ответил за 5 с» for each supplier that did not answer. */
export const silentSuppliers = (item: PartOffersItem) =>
  item.suppliers.filter((s) => s.status === 'failed').map((s) => `${s.name}: ${s.note}`)
