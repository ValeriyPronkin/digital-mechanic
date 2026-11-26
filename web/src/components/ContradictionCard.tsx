import type { ContradictionBlock, SourceItem } from '../api'
import { SourceChip } from './SourceChip'

/** «⚠ Противоречие в документации» (D-20): руководства расходятся — каждая формулировка дословно, со своей
 *  страницей; вывод, если есть правило заказчика, и совет уточнить у специалиста. Ни одну сторону не выбирает
 *  модель: блок собирает код из проверенных цитат страниц. */
export function ContradictionCard({
  block,
  sources,
  onOpen,
}: {
  block: ContradictionBlock
  sources: Record<string, SourceItem>
  onOpen: (s: SourceItem, quote?: string) => void
}) {
  return (
    <section
      className="space-y-3 rounded-xl border border-warn/60 bg-surface px-4 py-3"
      aria-label="Противоречие в документации"
    >
      <p className="font-semibold text-warn">⚠ Противоречие в документации — {block.title}</p>
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
      <p className="text-[13px] text-dim">{block.advice}</p>
    </section>
  )
}
