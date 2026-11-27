import type { ContradictionBlock, SourceItem } from '../api'
import { copy } from '../copy'
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
}: {
  block: ContradictionBlock
  sources: Record<string, SourceItem>
  onOpen: (s: SourceItem, quote?: string) => void
}) {
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
      {block.escalation && block.advice && <p className="text-[13px] text-dim">{block.advice}</p>}
    </section>
  )
}
