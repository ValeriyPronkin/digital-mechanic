// The tickets of a vehicle and the note of an outcome as the screen holds them, apart from React, so the
// two races they guard against are tested without a browser (web/tests/tickets.test.ts).

/** The list after `ticket` was saved or created on this screen: it takes the place of its older self. */
export function withTicket<T extends { id: number }>(list: T[], ticket: T): T[] {
  return [...list.filter((t) => t.id !== ticket.id), ticket].sort((a, b) => a.id - b.id)
}

/** The list once the server's answer arrives.
 *
 *  The answer was asked for when the screen opened. A ticket the mechanic has saved on this screen since
 *  then (`touched`: an outcome tapped, a ticket sent) is newer than its copy in that answer, so the local
 *  one stays; every other ticket comes from the answer. Without this an outcome tapped while the list was
 *  still loading was saved, and then painted over with the old one when the list came. */
export function mergeTickets<T extends { id: number }>(local: T[], fetched: T[], touched: ReadonlySet<number>): T[] {
  const kept = local.filter((t) => touched.has(t.id))
  const keptIds = new Set(kept.map((t) => t.id))
  return [...fetched.filter((t) => !keptIds.has(t.id)), ...kept].sort((a, b) => a.id - b.id)
}

/** Whether the note field holds something the store does not: `typed` is null while the field only shows
 *  the stored note. Spaces around the text are not a change. */
export function noteChanged(typed: string | null, stored: string | null | undefined): boolean {
  return typed !== null && typed.trim() !== (stored ?? '')
}

/** What the note field holds once a save has returned and the store has `stored`.
 *
 *  Back to showing the stored note (null) when that is what the field says; but text typed while the save
 *  was on its way is not what was saved, and stays in the field with «Сохранить» beside it. */
export function typedAfterSave(typed: string | null, stored: string | null | undefined): string | null {
  return noteChanged(typed, stored) ? typed : null
}
