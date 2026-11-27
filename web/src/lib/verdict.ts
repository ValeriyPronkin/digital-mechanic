import type { Block, VerdictBlock } from '../api'

/** The check's card can come twice: from its own quick request and in the chat stream. One card per check. */
export const isVerdictOf = (b: Block, sessionId: string | null | undefined): b is VerdictBlock =>
  b.kind === 'verdict' && (!sessionId || (b as VerdictBlock).session_id === sessionId)

/** The blocks of a turn with this card: it replaces the card of the same check where it stands; a new card goes
 *  first, above the answer, wherever it arrived from. */
export function withVerdict(blocks: Block[], card: VerdictBlock): Block[] {
  const at = blocks.findIndex((b) => isVerdictOf(b, card.session_id))
  if (at >= 0) return blocks.map((b, i) => (i === at ? card : b))
  return [card, ...blocks]
}

/** Whether the conversation already shows the card of this check: then there is nothing to ask for. */
export const shownVerdict = (turnBlocks: Block[][], sessionId: string | null | undefined): boolean =>
  turnBlocks.some((blocks) => blocks.some((b) => isVerdictOf(b, sessionId)))

/** For each turn, the checks whose card an earlier turn already shows. The card is drawn whole once, where
 *  it first stands (on «Получить результат», or with the first answer about that check); after that a turn
 *  carries one line that leads back to it. A card of another check is new, and is drawn whole. */
export function shownBefore(turnBlocks: readonly Block[][]): Set<string>[] {
  const seen = new Set<string>()
  return turnBlocks.map((blocks) => {
    const before = new Set(seen)
    for (const b of blocks) if (b.kind === 'verdict') seen.add((b as VerdictBlock).session_id)
    return before
  })
}

/** The id of the first card of a check, for the line that scrolls back to it. */
export const verdictAnchor = (sessionId: string) => `verdict-${sessionId}`
