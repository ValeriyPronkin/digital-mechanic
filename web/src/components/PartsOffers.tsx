import { Fragment } from 'react'
import type { PartsOffers as Offers } from '../api'
import { copy } from '../copy'
import { offerFacts, shownOffers, silentSuppliers, stockTone, webUrl } from '../lib/offers'

/** What the connected suppliers have for the parts still in the ticket (PR #84). For reference: none of it
 *  goes to ТОиР. A part looked up by its name, not by the designation from the manual, says so. */
export function PartsOffers({ offers, removed }: { offers: Offers | null | undefined; removed: Set<number> }) {
  const shown = shownOffers(offers, removed)
  if (!shown) return null // nothing to offer: no block at all, not an empty one
  return (
    <>
      <p className="text-[13px] text-mute">{copy.ticket.offersHint}</p>
      <ul className="divide-y divide-line">
        {shown.items.map((item) => (
          <li key={item.index} className="space-y-1 py-2">
            <p>{item.part}</p>
            {item.check && <p className="text-[13px] text-warn">{item.check}</p>}
            {item.offers.length > 0 ? (
              <ul className="space-y-1.5">
                {item.offers.map((o, k) => {
                  const url = webUrl(o.url)
                  const facts = offerFacts(o)
                  return (
                    <li key={k} className="border-l-2 border-line pl-2 text-[13px]">
                      <span className="block">{o.name ?? o.designation ?? item.query}</span>
                      <span className="block text-dim">
                        {facts.map((f, j) => (
                          <Fragment key={j}>
                            {j > 0 && ' · '}
                            <span className={f === o.available ? stockTone(o.in_stock) : undefined}>{f}</span>
                          </Fragment>
                        ))}
                        {o.supplier && (
                          <>
                            {facts.length > 0 && ' · '}
                            {url ? (
                              <a href={url} target="_blank" rel="noopener noreferrer" className="text-accent">
                                {o.supplier}
                              </a>
                            ) : (
                              o.supplier
                            )}
                          </>
                        )}
                      </span>
                    </li>
                  )
                })}
              </ul>
            ) : (
              item.note && <p className="text-[13px] text-dim">{item.note}</p>
            )}
            {silentSuppliers(item).map((s) => (
              <p key={s} className="text-[13px] text-dim">
                {s}
              </p>
            ))}
          </li>
        ))}
      </ul>
    </>
  )
}
