import type { ContradictionBlock, SourceItem } from '../api'
import { copy } from '../copy'
import { escalationView } from '../lib/contradiction'
import { SourceChip } from './SourceChip'

/** «Противоречие в документации» (D-20): руководства расходятся — каждая формулировка дословно, со своей
 *  страницей, и вывод, если есть правило заказчика. Ни одну сторону не выбирает модель: блок собирает код из
 *  проверенных цитат страниц. Карточка спокойная, без значка тревоги: расхождение — факт о документах, а не
 *  об этой машине. Строка под ним — передача главному механику (#93); прежний совет «уточните у
 *  производителя» (в нитях до #93, без `escalation`) не показывается: механик — специалист. */
export function ContradictionCard({
  block,
  sources,
  onOpen,
  onQueue,
}: {
  block: ContradictionBlock
  sources: Record<string, SourceItem>
  onOpen: (s: SourceItem, quote?: string) => void
  onQueue?: (number: number) => void // the chief mechanic's queue, at this contradiction; absent — no link
}) {
  const esc = escalationView(block)
  return (
    <section
      className="space-y-3 rounded-xl border border-line bg-surface px-4 py-3"
      aria-label={copy.contradiction.label}
    >
      <p className="font-semibold">{copy.contradiction.title(block.title)}</p>
      <ul className="space-y-3">
        {block.items.map((item, i) => {
          const source = item.handle ? sources[item.handle] : undefined
          return (
            <li key={i} className="space-y-1">
              <blockquote className="border-l-2 border-line pl-3">«{item.quote}»</blockquote>
              {item.note && <span className="block text-[13px] text-dim">{item.note}</span>}
              {source ? (
                <span className="-ml-[4px] flex flex-wrap">
                  <SourceChip source={source} verified onOpen={(s) => onOpen(s, item.quote)} />
                </span>
              ) : (
                <span className="block text-[13px] text-dim">{item.label}</span>
              )}
            </li>
          )
        })}
      </ul>
      <p>{block.conclusion}</p>
      {esc && (
        <div
          className={`space-y-1 rounded-lg border px-3 py-2 ${esc.tone === 'resolved' ? 'border-ok/50 bg-ok/10' : 'border-line bg-surface-2'}`}
        >
          {onQueue && esc.number !== null ? (
            <button
              type="button"
              onClick={() => esc.number !== null && onQueue(esc.number)}
              aria-label={`${esc.badge}. ${copy.contradiction.openQueue}`}
              className={`min-h-9 text-[13px] font-semibold underline-offset-2 hover:underline ${esc.tone === 'resolved' ? 'text-ok' : 'text-accent'}`}
            >
              {esc.badge}
            </button>
          ) : (
            <p className={`text-[13px] font-semibold ${esc.tone === 'resolved' ? 'text-ok' : 'text-dim'}`}>
              {esc.badge}
            </p>
          )}
          {esc.line && (
            <p className={`text-[13px] ${esc.tone === 'resolved' ? 'text-text' : 'text-dim'}`}>{esc.line}</p>
          )}
        </div>
      )}
    </section>
  )
}
