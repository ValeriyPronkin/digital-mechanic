// The ticket list and the note of an outcome under slow answers (#83): a late list must not paint over an
// outcome saved meanwhile, and a save that returns must not drop what was typed meanwhile. Run with `npm test`.
import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeTickets, noteChanged, typedAfterSave, withTicket } from '../src/lib/tickets.ts'

const ticket = (id: number, outcome: string | null = null, note: string | null = null) => ({
  id,
  outcome,
  outcome_note: note,
})

test('an outcome saved while the list was loading is not painted over when the list arrives', () => {
  // the card was drawn from the thread; the mechanic tapped «Другая неисправность» and the save returned
  const local = withTicket([], ticket(1, 'other_fault'))
  const late = [ticket(1, 'confirmed', 'Термостат заедал'), ticket(2)] // asked for before the tap
  assert.deepEqual(mergeTickets(local, late, new Set([1])), [ticket(1, 'other_fault'), ticket(2)])
})

test('tickets the mechanic did not touch come from the server, whatever the screen held', () => {
  const local = [ticket(1, null), ticket(3, 'confirmed')]
  const fetched = [ticket(1, 'confirmed'), ticket(2), ticket(3, 'not_confirmed')]
  assert.deepEqual(mergeTickets(local, fetched, new Set()), fetched)
  assert.deepEqual(mergeTickets([], fetched, new Set([7])), fetched)
})

test('a ticket sent while the list was loading stays, though the older list does not know it', () => {
  const local = withTicket([], ticket(5, null))
  assert.deepEqual(mergeTickets(local, [ticket(2)], new Set([5])), [ticket(2), ticket(5)])
})

test('a saved ticket takes the place of its older self and the list stays in order', () => {
  const list = [ticket(1), ticket(2), ticket(4)]
  assert.deepEqual(withTicket(list, ticket(2, 'confirmed')), [ticket(1), ticket(2, 'confirmed'), ticket(4)])
  assert.deepEqual(
    withTicket(list, ticket(3)).map((t) => t.id),
    [1, 2, 3, 4],
  )
})

test('the note is changed only when the field says something the store does not', () => {
  assert.equal(noteChanged(null, 'Течь сальника'), false) // the field only shows the stored note
  assert.equal(noteChanged('Течь сальника', 'Течь сальника'), false) // typed and typed back
  assert.equal(noteChanged('  Течь сальника  ', 'Течь сальника'), false)
  assert.equal(noteChanged('Течь сальника, заменили', 'Течь сальника'), true)
  assert.equal(noteChanged('', 'Течь сальника'), true) // cleared: the save removes the note
  assert.equal(noteChanged('', null), false)
  assert.equal(noteChanged('Течь сальника', undefined), true)
})

test('what was typed while a save was on its way stays in the field', () => {
  // «… — заменили» was sent; « в тот же день» was typed before the answer came
  assert.equal(
    typedAfterSave('Термостат заедал — заменили в тот же день', 'Термостат заедал — заменили'),
    'Термостат заедал — заменили в тот же день',
  )
  // nothing typed meanwhile: the field goes back to showing the stored note
  assert.equal(typedAfterSave('Термостат заедал — заменили', 'Термостат заедал — заменили'), null)
  assert.equal(typedAfterSave(' Термостат заедал — заменили ', 'Термостат заедал — заменили'), null)
  assert.equal(typedAfterSave(null, 'Термостат заедал'), null) // an outcome was tapped, the note untouched
  assert.equal(typedAfterSave('', null), null) // cleared and saved as cleared
})
