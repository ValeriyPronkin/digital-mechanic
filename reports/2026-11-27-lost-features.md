# Что потерялось при переходе на интерфейс /v2 (27.11)

**Итог.** Основной путь ТЗ в /v2 есть: карточка по `status`, плашка помех, посторонний текст, несовместимый код, заявка с подтверждением, страница руководства с цитатой, голос, озвучка, паспорт ответа, парк и график. Потери — в функциях, у которых сервер готов, а экрана нет. Важнее всего четыре. Первая — запчасти и инструмент цветом: договорились, сервер размечает только в ветке `s72-parts-tools-spans` (ещё не на main), в `web/src` нет ни одного `spans`. Вторая — экран главного механика для очереди противоречий (письмо, «Отправить», «Решение», журнал): API на main, в `web/src` нет `/contradictions`. Третья — история обращений по машине с «Продолжить» (B1): API на main, экрана нет. Четвёртая — выгрузка для рекламации: API на main, экрана нет. Остальное мелкое: номер «№ N» и цвет «решено» в карточке противоречия, версия в подвале, паспорт карточки проверки.

Код /v2 сверял с `origin/main` (293bc7c). Локальная ветка `e2e-video-scenes` отстаёт от main на 183 коммита, в ней нет `LanguageSwitch`, `PartsOffers`, `TicketRegister` и других файлов.

## Таблица

Оценки — это **оценки**, в часах работы одного человека, без ревью и CI.

| Функция | Где была (v1 / Никита / только API) | В /v2 сейчас | Важность | Оценка, ч | Примечание |
|---|---|---|---|---|---|
| Карточка проверки по `status`: норма, «норма, повторить раньше» (≥ 0,30), отклонение, предварительно, сбой | v1 `src/service/static/index.html` (`screenCard`); Никита `web/src/components/VerdictCard.tsx` | есть — `web/src/components/VerdictCard.tsx`, `web/src/lib/checks.ts` (`case: normal / normal_raised / anomaly / preliminary / failed`) | ТЗ С1–С3, видео | 0 | — |
| Сбой записи: без выводов и без заявки | v1 `index.html` (быстрая кнопка «Как правильно повторить запись?»); Никита README, С3 | есть — `VerdictCard.tsx`, `lib/checks.ts` (`check_failed`) | ТЗ С2 (сбой) | 0 | — |
| Плашка `warning` «запись с помехами» | v1 `index.html` (`card.banners`) | есть — `VerdictCard.tsx`, `lib/checks.ts` (`signal_quality`, `quality_word`) | ТЗ, приёмка 17 `warning` | 0 | — |
| Несовместимый код × двигатель: факт о конструкции, без заявки | v1 `index.html` (`design_fact`); Никита README, «Неисправность, которой на двигателе нет» | есть — `VerdictCard.tsx` (`case === 'mismatch'`), `GuideCard.tsx` (доказательство и «Скопировать» рекомендацию) | ТЗ С4 | 0 | — |
| Посторонний текст в `description` — отдельно и серым | v1 `index.html` (`ml_injection`); Никита README | есть — `VerdictCard.tsx` (`foreign_text`, зачёркнуто, свёрнуто), `Withdrawn.tsx` | ТЗ (инъекции) | 0 | — |
| Заявка: черновик → подтверждение → ТОиР | v1 `index.html` (`draftCard`, `/api/tickets`); Никита `TicketSheet.tsx` | есть — `TicketSheet.tsx`, `TicketCard.tsx`, `api.ts` (`/tickets/{id}/approve`, `/reject`) | ТЗ С1, видео | 0 | Приоритет выбирает механик; галочка «вывод предварительный» есть (`TicketSheet.tsx`) |
| Печать заявки, реестр заявок, итог дефектовки, `outcomes.csv` | Никита README (С4, «Заявки»), `TicketPrint.tsx`, `TicketRegister.tsx` | есть — `TicketPrint.tsx`, `TicketRegister.tsx` (фильтры `all / waiting / recorded`), `api.ts` (`OUTCOMES_EXPORT`) | удобство, B3 | 0 | Перенесено от Никиты |
| Поставщики под строками запчастей (`parts_offers`) | v1 `index.html` (`partItem`, `/api/parts`); API PR #84 | есть — `PartsOffers.tsx` в `TicketSheet.tsx` | удобство | 0 (web) | На стенде «каталог не подключён», пока Валерий не добавит `PARTS_SUPPLIERS` в `stand.yml` (STATUS, «Ждёт человека») |
| **Запчасти и инструмент в ответе — своим цветом** | новая договорённость 27.11; сервер — ветка `origin/s72-parts-tools-spans` (поверх `s71-parts-tools`), поле `spans` события `text`, раздел 8 `docs/api-v2-web.md` в этой ветке | **нет** — `grep -rn spans web/src` пусто | видео, удобство | 1–1,5 (web) + слияние s71/s72 | Ветки s71 и s72 не на main и без PR в `gh pr list`. Без них красить нечего |
| Паспорт ответа: шаги, фрагменты, токены, ₽, правила, «Скачать JSON» | v1 `index.html` (`passportBlock`) | есть — `ActionLog.tsx` (`PassportSection`), `lib/passport.ts` | видео (сцена «паспорт ₽»), ТЗ (журнал токенов) | 0 | — |
| Паспорт карточки проверки («Как получена карточка») | v1 `index.html` (`card.passport`) | нет — в `VerdictCard.tsx` нет `passport`; `GET /vehicles/{id}/verdict` (`api_v2.py`) паспорт не отдаёт | удобство | 1–1,5 (сервер + web) | Карточка без модели, 0 ₽; ценность для жюри невелика |
| Уровень механика | v1 `index.html` (переключатель «Опытный / Пошагово», вопрос при первом входе) | есть, переделан — `lib/level.ts`, `VehicleScreen.tsx` (стр. 159–180: «Уровень: …», «Подробнее / Короче»), `main.tsx` убирает `dm-level` | удобство | 0 | Переключатель в шапке убран сознательно (#91, `docs/api-v2-web.md` §2) |
| Голосовой ввод | v1 `index.html` (`startRecording`, «Исправить»); Никита README | есть — `useVoice.ts`, `lib/wav.ts`, `api.ts` (`/transcribe?lang=`) | видео, удобство | 0 | Текст сначала в поле, отправка — кнопкой |
| Озвучка ответа | v1 `index.html` (`speak`, «Повторить», «Стоп») | есть — `SpeakButton.tsx` («Прослушать», стоп), `lib/speech.ts` (с `lang`) | удобство | 0 | Кнопки «Повторить» нет: повтор — тем же нажатием |
| «Как в руководстве»: страница с цитатой | v1 `index.html` (`quoteButton`, картинка страницы); Никита README (строка отмечена на странице) | есть — `PageSheet.tsx` (картинка, отметка строки, текст, если картинка не пришла), `SourceChip.tsx` | ТЗ (ссылка на страницу), видео | 0 | — |
| Язык ответа и «Показать по-русски» | API PR #83 | есть — `LanguageSwitch.tsx`, `VehicleScreen.tsx` (`back_translation`), `lib/lang.ts` | удобство | 0 | — |
| Противоречие в руководствах: обе формулировки со страницами | v1 — ответ модели; Никита README («Расхождение в руководствах», `M333YK47`) | есть — `ContradictionCard.tsx` | видео (сцена «противоречие») | 0 | — |
| Противоречие: «№ N» на экран главного механика и решение рядом другим цветом | API PR #93 (`escalation.number`, `escalation.resolved`) | частично — `ContradictionCard.tsx` показывает только `advice`; `number` и `resolved` не используются | B3, видео | 0,5–1 | Ссылка «№ N» нужна, когда появится экран очереди |
| **Экран главного механика: очередь противоречий, письмо, «Отправить», «Решение», журнал** | только API — `src/service/api_v2.py` (`/contradictions`, `/letter`, `/send`, `/resolve`, `/journal`), PR #93; `docs/api-v2-web.md` §6, бэклог № 6 | **нет** — `grep -rn contradictions web/src` пусто | B3, видео | 3–4 (web) | Сервер на main. Письмо сервер не отправляет: «Отправить» — отметка |
| Сводка парка / режим главного механика | v1 `src/service/static/fleet.html` (сводка, статусы); Никита README С4 | есть — `FleetList.tsx` (роль `chief`), `App.tsx`, `lib/fleet.ts`, `api.ts` (`/api/v2/fleet`) | B3, ТЗ С4 (Никита) | 0 | — |
| История проверок и график `anomaly_score` | v1 `fleet.html` (`chart`: разрыв на сбое, пороги 0,30 и 0,85); Никита `ScoreChart.tsx` | есть — `ScoreChart.tsx` (с `trend`), `VehicleScreen.tsx` стр. 510 | B2 | 0 | — |
| Заявки по машине | v1 `fleet.html` («Заявки по машине») | есть — `VehicleScreen.tsx` стр. 527, `api.ts` (`/vehicles/{id}/tickets`) | B1, удобство | 0 | — |
| **История обращений по машине и «Продолжить»** | только API — `api_v2.py` (`GET /vehicles/{id}/threads`, `POST /threads/{tid}/resume`), PR #92; `docs/api-v2-web.md` §5, бэклог № 4 | **нет** — в `web/src` есть только `/threads/current` (`api.ts` стр. 440); `/resume` нигде не вызывается | B1 | 2–3 (web) | Время показывать по Москве; 404 «срок хранения истёк» |
| **Выгрузка нити для рекламации (JSON / HTML, целостность)** | только API — `api_v2.py` (`/threads/{tid}/export`, `?format=html`), PR #92 | **нет** — пути `/export` в `web/src/api.ts` нет | B1, удобство | 1 (web, вместе с историей) | `integrity.ok = false` — красным |
| Версия в подвале | только API — `/health` → `build` (PR #88, #89); бэклог № 7 | нет — `git_sha` и `/health` в `web/src` не встречаются | удобство (жюри видит версию) | 0,5 | — |
| Быстрые вопросы под карточкой | v1 `index.html` (`chatBlock`, `quick`) | есть — `copy.ts` (`quick`) | удобство | 0 | — |

## 5 главных пунктов

1. **Запчасти и инструмент своим цветом в ответе** — договорённость 27.11 и заметно в кадре. Сейчас в `web/src` поля нет, сервер в неслитых ветках s71 и s72. Оценка: 1–1,5 ч web, плюс PR и слияние s71/s72.
2. **Экран главного механика: очередь противоречий** (письмо, «Отправить», «Решение», журнал) — закрывает B3 и делает противоречие историей до конца, а не тупиком. Сервер на main. Оценка: 3–4 ч web.
3. **История обращений по машине и «Продолжить»** — прямой ответ на B1 «память по машине», сервер на main. Оценка: 2–3 ч web.
4. **Выгрузка для рекламации (HTML для печати, JSON, целостность)** — дешёвый довесок к пункту 3, жюри видит неизменяемый журнал. Оценка: 1 ч web.
5. **«№ N» и «решено» в карточке противоречия** — связывает сцену противоречия механика с экраном главного механика. Оценка: 0,5–1 ч web (после пункта 2).

## Как проверял

- Правила и контракты — `CLAUDE.md`; бэклог web — `docs/api-v2-web.md` на main; готовность видео — `STATUS.md` на main.
- Код /v2 и сервер — снимок `origin/main` (293bc7c) через `git archive origin/main web/src docs/api-v2-web.md src/service/api_v2.py src/service/static` во временную папку. Проверка «есть / нет» — `grep -rn` по `web/src` на `threads`, `resume`, `export`, `contradictions`, `escalation`, `parts_offers`, `spans`, `git_sha`, `/health`, `passport`, `foreign_text`, `mismatch`, `back_translation`, `level_used` и другие; найденное открывал (`ContradictionCard.tsx`, `ActionLog.tsx`, `App.tsx`, `api.ts`).
- Маршруты сервера — `grep "@router" src/service/api_v2.py`.
- v1 — `git show origin/main:src/service/static/index.html` (700 строк) и `git show origin/main:src/service/static/fleet.html` (191 строка): файлы ещё на main.
- Разметка запчастей и инструмента — `git log origin/main..origin/s72-parts-tools-spans`, `git diff origin/main...origin/s72-parts-tools-spans -- docs/api-v2-web.md`; `gh pr list` — PR для s71/s72 нет.
- Прототип Никиты — только `gh api repos/pronkinnikita/digital-mechanic/...`: дерево файлов, `README.md` («Что проверить», ограничения), `web/src/components/Counter.tsx`, `Header.tsx`, `web/src/lib/route.ts`.
- **Не проверял:** интерфейс не запускал, сцены видео в браузере не смотрел. Что функция работает на стенде, не проверено, только наличие кода. Не сверял, открывает ли /v2 машину из реестра заявок на нужной проверке (у Никиты — `route.ts`, `?ticket=`). Сценарий видео отдельным файлом на main не нашёл; важность «видео» — по `STATUS.md` и сценам `make e2e` (С1 до заявки, С3, противоречие, паспорт ₽).
