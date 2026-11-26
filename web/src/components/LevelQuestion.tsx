import { setLevel, type Level } from '../lib/level'

/** The first visit: one question, then the switch at the input field (#17). Big targets: a mechanic taps it
 *  with a knuckle. The answer is kept on the device. */
export function LevelQuestion({ onDone }: { onDone: () => void }) {
  const pick = (l: Level) => {
    setLevel(l)
    onDone()
  }
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-bg/90 p-4"
      role="dialog"
      aria-modal
      aria-labelledby="level-q"
    >
      <section className="w-full max-w-md space-y-3 rounded-xl border border-line bg-surface p-5">
        <h2 id="level-q" className="text-[22px] leading-tight font-semibold">
          Как объяснять: коротко или по шагам?
        </h2>
        <button
          type="button"
          onClick={() => pick('expert')}
          className="block min-h-16 w-full rounded-lg border border-line px-4 py-3 text-left hover:border-accent"
        >
          <span className="block text-[17px] font-semibold">Коротко</span>
          <span className="block text-[13px] text-dim">Я опытный: значение, инструмент, страница</span>
        </button>
        <button
          type="button"
          onClick={() => pick('steps')}
          className="block min-h-16 w-full rounded-lg border border-line px-4 py-3 text-left hover:border-accent"
        >
          <span className="block text-[17px] font-semibold">По шагам</span>
          <span className="block text-[13px] text-dim">Подробно: шаги, безопасность, термины простыми словами</span>
        </button>
        <p className="text-[13px] text-mute">Поменять можно в любой момент — у поля вопроса.</p>
      </section>
    </div>
  )
}
