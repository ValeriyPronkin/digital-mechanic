// How the thread keeps the reader's place. No imports: the unit tests load this module in Node as it is.

/** The class of the thread's scroll area that says whether the browser may keep the reader's place by
 *  itself (scroll anchoring).
 *
 *  While an answer runs it may not: after the thread has been scrolled, anchoring moves the view down with
 *  every piece of the answer, and the question that was put at the top ends above the view, 108 px on a
 *  phone and more than a screen on a laptop. When nothing runs it may, and it is wanted: a ticket card that
 *  loads late above a restored conversation, or a disclosure opened above the reader's place, would
 *  otherwise push the text under the eye down by its height. The class name is spelled out whole so that
 *  Tailwind finds it. */
export function anchoringWhile(answerRuns: boolean): string {
  return answerRuns ? '[overflow-anchor:none]' : ''
}
