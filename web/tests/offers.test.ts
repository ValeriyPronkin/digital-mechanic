// The suppliers' offers on the ticket sheet (parts_offers, PR #84). Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import type { PartOffer, PartOffersItem, PartsOffers } from '../src/api.ts'
import { offerFacts, priceRub, shownOffers, silentSuppliers, stockTone, webUrl } from '../src/lib/offers.ts'

const NBSP = ' '
const offer = (o: Partial<PartOffer> = {}): PartOffer => ({
  supplier: 'Демо-склад (вымышленный)',
  name: 'Втулка коромысла (демо)',
  designation: '236-1007118',
  available: 'есть, 12 шт.',
  in_stock: true,
  price_rub: 100,
  lead_days: 1,
  url: null,
  ...o,
})
const item = (index: number, o: Partial<PartOffersItem> = {}): PartOffersItem => ({
  index,
  part: `Деталь ${index}`,
  query: `Деталь ${index}`,
  by: 'name',
  check: 'по названию, проверьте',
  note: '',
  offers: [offer()],
  suppliers: [{ name: 'Демо-склад (вымышленный)', status: 'ok', note: '' }],
  ...o,
})
const connected = (items: PartOffersItem[], note = ''): PartsOffers => ({ connected: true, note, items })

test('no parts in the draft, or a draft saved before the field: nothing is shown', () => {
  assert.equal(shownOffers(null, new Set()), null)
  assert.equal(shownOffers(undefined, new Set()), null)
})

test('no supplier connected: the server’s note, said plainly, and no offers', () => {
  const off = { connected: false, note: 'Каталог поставщика не подключён', items: [] }
  assert.deepEqual(shownOffers(off, new Set()), { note: 'Каталог поставщика не подключён', items: [] })
})

test('a part the mechanic removed from the ticket loses its offers; all removed — nothing is shown', () => {
  const offers = connected([item(0), item(1), item(2)])
  assert.deepEqual(
    shownOffers(offers, new Set([1]))?.items.map((i) => i.index),
    [0, 2],
  )
  assert.equal(shownOffers(offers, new Set([0, 1, 2])), null)
})

test('suppliers that did not answer are named; those that answered are not', () => {
  const it = item(0, {
    suppliers: [
      { name: 'Демо-склад', status: 'ok', note: '' },
      { name: 'Демо-API', status: 'failed', note: 'не ответил за 5 с' },
      { name: 'Третий', status: 'empty', note: 'позиции нет' },
    ],
  })
  assert.deepEqual(silentSuppliers(it), ['Демо-API: не ответил за 5 с'])
})

test('prices read as roubles, whole or with kopecks, and a missing price is left out', () => {
  assert.equal(priceRub(100), `100${NBSP}₽`)
  assert.equal(priceRub(1250), `1${NBSP}250${NBSP}₽`)
  assert.equal(priceRub(99.5), `99,50${NBSP}₽`)
  assert.equal(priceRub(null), null)
  assert.deepEqual(offerFacts(offer({ price_rub: null, lead_days: null })), ['236-1007118', 'есть, 12 шт.'])
  assert.deepEqual(offerFacts(offer()), ['236-1007118', 'есть, 12 шт.', `100${NBSP}₽`, 'срок 1 дн.'])
})

test('availability is coloured by what the server read from it, and only web links are followed', () => {
  assert.equal(stockTone(true), 'text-ok')
  assert.equal(stockTone(false), 'text-warn')
  assert.equal(stockTone(null), 'text-dim')
  assert.equal(webUrl('https://example.org/p/1'), 'https://example.org/p/1')
  assert.equal(webUrl('javascript:alert(1)'), null)
  assert.equal(webUrl(null), null)
})
