# Контракт `/api/v2` для интерфейса (`web/`) — новые поля и бэклог

Для Никиты. Владелец `web/` — он, серверная часть и этот контракт — команда. Здесь только то, что добавилось после первой версии интерфейса v2 (#52). Общий поток чата (`thread`, `tool_started` / `tool_result`, `sources`, `text`, `verification`, `ticket_pending`, `usage`, `passport`, `speech`, `done`) не изменился.

**Где поле.** У каждого поля стоит, слито оно уже или нет:
- **на main** — уже есть;
- **после слияния #N** — появится, когда PR #N сольют. До того поля нет: интерфейс должен работать и без него.

Неизвестные поля и события интерфейс пропускает — так договорились в #52.

## 1. Язык ответа · на main (#83, #86)

**Список языков** — для переключателя:
```
GET /api/v2/languages
→ [{"lang": "ru", "name": "Русский", "voice_input": true, "voice_output": true},
   {"lang": "uz", "name": "Oʻzbekcha", "voice_input": true, "voice_output": true},
   {"lang": "tg", "name": "Тоҷикӣ", "voice_input": false, "voice_output": false},
   {"lang": "hi", "name": "हिन्दी", "voice_input": false, "voice_output": false}, …]
```
Языки: `ru`, `uz`, `uz-cyrl`, `tg`, `kk`, `ky`, `en`, `hi`.

**Выбор механика:**
```
POST /api/v2/chat {"vehicle_id": "B418HK98", "session_id": "S-0009", "message": "…", "lang": "uz"}
```
Если `lang` нет или он `"auto"`, ответ приходит на языке вопроса.

**События в потоке:**
```
data: {"type": "back_translation", "text": "Тот же ответ по-русски [S1] …"}
data: {"type": "language", "lang": "uz", "name": "Oʻzbekcha", "voice_input": true, "voice_output": true}
data: {"type": "speech", "text": "…", "sig": "<64>", "url": "/api/voice/speak", "lang": "uz-UZ"}
```
- `back_translation` приходит вслед за `text`, только если ответ не по-русски. Это кнопка **«Показать по-русски»**: показывает текст события, цифры в нём проверены. Механик его не ждёт, событие может прийти позже ответа.
- `language` — на каком языке ответ и есть ли голос. Если `voice_output=false`, кнопку «Прослушать» скрыть или подписать «Озвучки на этом языке нет».
- **Озвучка:** в `POST /api/voice/speak` передавать `{"text", "sig", "lang": speech.lang}`.
- **Распознавание:** `POST /api/v2/transcribe?lang=uz|kk|en` (по умолчанию `ru`). Если `voice_input=false`, подпись «голосом — по-русски».

## 2. Уровень механика · после слияния #91

```
POST /api/v2/chat {…, "level": "auto"}     // auto | novice | mechanic | master; прежние expert/steps принимаются
data: {"type": "text", "text": "…", "round": 1,
       "level_used": "novice", "level_word": "Новичок",
       "level_reason": "по вопросу: «как сделать / что это / чем» — шаги, инструмент, безопасность, проверка"}
```
- Уровень определяется **по вопросу, на каждый вопрос заново**. Решение Валерия: за механиком уровень **не запоминается** — смены, подмены.
- **По умолчанию слать `level: "auto"`.** Ключ `dm-level` в `localStorage` и вопрос при первом входе (`LevelQuestion`, #69) убрать.
- Переключатель «Новичок / Механик / Мастер» переспрашивает **только этот** вопрос с выбранным уровнем. «Подробнее / Короче» (#70): Подробнее → на уровень ниже, Короче → выше.
- Те же `level_used`, `level_word`, `level_reason` — в стенограмме нити (`GET /threads/current`) и в паспорте (`question.level`, `question.level_reason`).

## 3. Предложения поставщиков в заявке · на main (#84)

В событии `ticket_pending` и в ответе `POST /tickets/{id}/approve`:
```
"parts_offers": null                       // в черновике нет запчастей
  | {"connected": false, "note": "Каталог поставщика не подключён: …", "items": []}   // на стенде сейчас так
  | {"connected": true, "note": "",
     "items": [{"index": 0, "part": "Втулка коромысла (236-1007118), стр. 169", "query": "236-1007118",
                "by": "designation", "check": "",          // by: "name" → check: "по названию, проверьте"
                "note": "",
                "offers": [{"supplier": "Демо-склад (вымышленный)", "designation": "236-1007118",
                            "name": "Втулка коромысла (демо)", "available": "есть, 12 шт.", "in_stock": true,
                            "price_rub": 100.0, "lead_days": 1, "url": null}],   // уже отсортированы
                "suppliers": [{"name": "Демо-склад (вымышленный)", "status": "ok", "note": ""},
                              {"name": "Демо-API (вымышленный)", "status": "failed", "note": "не ответил"}]}]}
```
- Показывать под строкой запчасти: `index` — номер в `payload.spare_parts`.
- Если `check` не пуст, рядом пометка «по названию, проверьте».
- Поставщик со статусом `failed` — серой строкой «не ответил».
- Если `connected=false`, одна строка `note`.

Локально с двумя вымышленными поставщиками: `make parts-demo`, затем `PARTS_SUPPLIERS=data/demo/suppliers make run-local`.

## 4. Противоречия: баннер «Передано главному механику» · после слияния #93

Блок `tool_result` с `block.kind == "contradiction"`:
```
{"kind": "contradiction", "title": "когда регулировать тепловые зазоры клапанов",
 "items": [{"handle": "S1", "label": "РЭ — …, стр. 31", "quote": "…", "manual_id": "yamz-236-re", "pdf_page": 31, "note": null}, …],
 "conclusion": "Регулировать зазоры на холодном двигателе … Основание — …",
 "advice": "Передано главному механику на решение (№ 1). Пока — безопасное правило: по выводу выше.",
 "escalation": {"line": "<то же>", "number": 1, "resolved": false}}
```
- **До #93** в `advice` был совет «уточните у производителя». После #93 там строка эскалации: старый интерфейс покажет её без правок.
- `escalation.resolved = true` → строка вида «Решение по противоречию (источник: завод-изготовитель, 27.11.2026): … Основание: …». Показывать **рядом** с обеими формулировками, не вместо них, другим цветом («решено»).
- `escalation.number` — ссылка «№ N» на экран главного механика (раздел 6).

## 5. История обращений по машине и продолжение нити · после слияния #92

```
GET /api/v2/vehicles/B418HK98/threads
→ [{"thread_id": "a1b2c3d4e5f60718", "started_at": "2026-11-27T08:40:00+00:00", "updated_at": "…",
    "session_id": "S-0009", "topic": "Что с двигателем?", "status": "ticket_sent",   // open | ticket_pending | ticket_sent
    "ticket_id": "TKT-0007", "records": 3}]

POST /api/v2/threads/a1b2c3d4e5f60718/resume {"vehicle_id": "B418HK98"}
→ как GET /threads/current: {"thread_id", "session_id", "transcript", "sources", "pending"}; ставит cookie
```
- Время — ISO UTC, показывать по Москве.
- `topic` — первый вопрос нити, без ПДн, не длиннее 80 знаков.
- Нить продолжается с любого телефона: после `resume` следующий `POST /chat` без `new_thread` идёт в эту нить.
- Срок хранения — настройка `CASE_RETENTION_DAYS` (по умолчанию 3 года). Старше — 404 «срок хранения истёк».

**Выгрузка для рекламации:**
```
GET /api/v2/vehicles/B418HK98/threads/a1b2c3d4e5f60718/export
→ {"vehicle_id", "engine", "thread": {…}, "integrity": {"ok": true, "detail": "цепочка цела: записей 3"},
   "retention_days": 1095,
   "records": [{"seq": 1, "kind": "answer", "at": "…", "question": "…", "answer": "…",
                "pages": [{"handle": "S1", "manual": "…", "pdf_page": 42, "quote": "…"}],
                "provider": "deepseek", "models": ["…"], "index_version": "…", "commit": "…",
                "sha256": "…", "prev_sha256": "…"},
               {"seq": 3, "kind": "ticket", "ticket_id": "TKT-0007", …}]}
GET …/export?format=html     → страница для печати (открыть в новой вкладке)
```
`integrity.ok=false` — запись правили или удалили. Показать красным.

## 6. Очередь противоречий у главного механика · после слияния #93

```
GET  /api/v2/contradictions?status=open          // open | sent | resolved | all
→ [{"number": 1, "id": "yamz-236-valve-clearance-timing", "status": "open", "engine": "ЯМЗ-236М2",
    "title": "…", "formulations": [{"label", "manual_id", "pdf_page", "quote"}], "rule": "…" | null,
    "safe_rule": "…", "count": 4, "vehicles": ["B418HK98"], "first_seen": "…", "last_seen": "…",
    "sent": [{"to": "manufacturer", "by": "…", "at": "…", "text": "…", "channel": "none"}],     // после «Отправить»
    "resolution": {"text", "by", "at", "source", "document"}}]                                 // после «Решение»
GET  /api/v2/contradictions/1/letter?to=manufacturer|support → {"to", "text", "channel"}   // черновик письма
POST /api/v2/contradictions/1/send    {"to": "manufacturer", "by": "главный механик", "text": "правленый текст (необязательно)"}
POST /api/v2/contradictions/1/resolve {"text": "…", "by": "…", "source": "manufacturer|support|chief_mechanic", "document": "письмо № …"}
GET  /api/v2/contradictions/journal   → события sent / resolved по порядку (только добавление)
```
- **Письмо сервер не отправляет.** «Отправить» — это отметка с текстом. Сам текст главный механик копирует или отправляет по каналу пилота (`channel`).

## 7. Версия в подвале · после слияния #88 (+ #89 — workflow)

```
GET /health → {…, "build": {"git_sha": "…40…", "git_sha_short": "2ce108f", "built_at": "2026-11-27T10:30:00Z" | null,
                            "source": "image" | "git" | "unknown"}}
```
Подвал: «версия 2ce108f · 27.11 13:30». При `source: "unknown"` — «версия неизвестна».

## Бэклог `web/` — по приоритету для видео

| № | Что | Поля | Готовность сервера |
|---|---|---|---|
| 1 | Переключатель языка и «Показать по-русски» | раздел 1 | на main |
| 2 | `level: "auto"`, убрать `dm-level` и `LevelQuestion`, показать «Уровень: …» и переключатель для этого вопроса | раздел 2 | после #91 |
| 3 | Баннер противоречия: строка эскалации, «№ N», решение рядом с формулировками | раздел 4 | после #93 (`advice` — уже сейчас) |
| 4 | История обращений по машине: «Продолжить», «Выгрузить для рекламации» | раздел 5 | после #92 |
| 5 | Предложения поставщиков под строками запчастей в листе заявки | раздел 3 | на main (на стенде — «не подключён») |
| 6 | Экран главного механика: очередь противоречий, письмо, «Отправить», «Решение», журнал | раздел 6 | после #93 |
| 7 | Версия в подвале | раздел 7 | после #88 и #89 |

Правила работы в `web/` — [`docs/web-workflow.md`](web-workflow.md).
