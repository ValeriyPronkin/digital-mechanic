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
