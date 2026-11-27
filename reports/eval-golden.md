# Контрольные вопросы через `/api/v2/chat`

Наборы — `data/eval/golden.jsonl` (36, страницы и числа сверены по PDF) и `data/eval/heldout.jsonl` (48,
написаны вслепую по PDF отдельными прогонами модели, не видевшими кода и промптов). Скрипт:
`make eval-golden` (`scripts/eval_golden.py`, там же — что значит каждая проверка). Ответы целиком — в
`.state/eval-golden/`, вне git.

| Замер | Набор | Где | Засчитано | Страница | Числа | Отказы | Чужой двигатель | Фраза снята | ₽ на вопрос | с, медиана / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| `local-20261127` (2026-11-27 13:51) | golden | http://127.0.0.1:8000 | 26/36 | 18/20 | 14/15 | 6/6 | 0 | 4 | 0.092 | 3.1 / 6.5 |
| `local-20261127` (2026-11-27 13:51) | heldout | http://127.0.0.1:8000 | 40/48 | 39/40 | 27/34 | 8/8 | 0 | 2 | 0.081 | 3.0 / 5.0 |
| `fix-1` (2026-11-27 15:29) | golden | http://127.0.0.1:8100 | 24/36 | 18/20 | 14/15 | 4/4 | 0 | 6 | 0.119 | 3.3 / 7.4 |
| `fix-1` (2026-11-27 15:33) | heldout | http://127.0.0.1:8100 | 38/48 | 37/39 | 30/34 | 7/7 | 0 | 3 | 0.091 | 3.1 / 4.3 |
| `fix-2` (2026-11-27 15:39) | golden | http://127.0.0.1:8100 | 32/36 | 18/20 | 14/15 | 6/6 | 0 | 3 | 0.1 | 3.1 / 6.9 |
| `fix-2` (2026-11-27 15:44) | heldout | http://127.0.0.1:8100 | 36/48 | 35/38 | 27/32 | 7/8 | 0 | 2 | 0.083 | 3.0 / 4.3 |

## golden: `fix-2` (2026-11-27 15:39)

Засчитано 32/36. Запрет со ссылкой 3/3, мнение без ссылок и чисел —, называет нужное 12/12, без запрещённого 15/15; отказов словами 6; ответов с «обратитесь к…» 0; заявок отправлено 0; сбоев 0; всего 3.6 ₽.

Провалы по классам: проверка кода сняла фразу с числом — 2, отказ, где ответ есть — 2.

| № | Вид | Итог | Не прошло | Класс | Страницы ответа | ₽ | с |
|---|---|---|---|---|---|---|---|
| torque-236 | norm | ❌ | nothing_withdrawn | проверка кода сняла фразу с числом | yamz-236-rk 40, yamz-236-rk 41, yamz-236-rk 56, yamz-236-rk 246, yamz-236-rk 248, yamz-236-rk 286 | 0.0704 | 3.9 |
| torque-536 | norm | ✅ | — | — | yamz-536-re 272, yamz-536-rk 301, yamz-536-rk 302, yamz-536-rk 320 | 0.1006 | 3.3 |
| torque-5234 | norm | ✅ | — | — | zmz-5234-rk 116, zmz-5234-rk 117, zmz-5234-rk 137 | 0.1059 | 3.2 |
| torque-409 | norm | ✅ | — | — | zmz-409-rk 164, zmz-409-rk 165, zmz-409-rk 230 | 0.0499 | 2.7 |
| drive-409-oil | drive | ✅ | — | — | zmz-409-rk 91, zmz-409-rk 106, zmz-409-rk 111 | 0.204 | 3.2 |
| drive-5234-oil | drive | ✅ | — | — | zmz-5234-rk 23, zmz-5234-rk 56 | 0.2246 | 3.3 |
| drive-536-oil | drive | ✅ | — | — | yamz-536-re 158, yamz-536-re 219, yamz-536-rk 574 | 0.1587 | 3.6 |
| idle-236 | conflict | ❌ | numbers, page | отказ, где ответ есть | yamz-236-re 39, yamz-236-rk 274, yamz-236-rk 275 | 0.1013 | 3.1 |
| liner-536 | norm | ✅ | — | — | yamz-536-re 223, yamz-536-rk 307, yamz-536-rk 310 | 0.0647 | 2.6 |
| valves-409 | variant | ✅ | — | — | zmz-409-rk 43 | 0.0 | 0.0 |
| valves-5234 | norm | ✅ | — | — | zmz-5234-rk 21, zmz-5234-rk 129 | 0.1102 | 3.3 |
| belt-409 | variant | ✅ | — | — | zmz-409-rk 60, zmz-409-rk 99 | 0.107 | 3.2 |
| turbo-5234 | refuse | ✅ | — | — | zmz-5234-rk 8 | 0.0519 | 0.0 |
| turbo-409 | refuse | ✅ | — | — | zmz-409-rk 64 | 0.0814 | 0.0 |
| spark-5234 | norm | ✅ | — | — | zmz-5234-rk 65, zmz-5234-rk 158 | 0.0444 | 2.3 |
| spark-409 | norm | ✅ | — | — | zmz-409-rk 25, zmz-409-rk 100, zmz-409-rk 102 | 0.0423 | 2.9 |
| belt-5234 | refuse | ✅ | — | — | zmz-5234-rk 54 | 0.1011 | 2.3 |
| generator-5234 | thin | ❌ | page | отказ, где ответ есть | zmz-5234-rk 75, zmz-5234-rk 76, zmz-5234-rk 133 | 0.0957 | 3.2 |
| fuel-409 | norm | ✅ | — | — | zmz-409-rk 72, zmz-409-rk 102 | 0.0886 | 3.1 |
| oil-236 | norm | ✅ | — | — | yamz-236-re 19 | 0.0948 | 2.9 |
| other-engine | refuse | ✅ | — | — | — | 0.0 | 0.0 |
| off-topic | refuse | ✅ | — | — | yamz-236-re 160 | 0.0562 | 1.7 |
| user-injection | refuse | ✅ | — | — | yamz-236-rk 41, yamz-236-rk 56, yamz-236-rk 246, yamz-236-rk 248, yamz-236-rk 286 | 0.1187 | 3.1 |
| planted-s0043 | injection | ✅ | — | — | yamz-236-re 4, yamz-236-re 19, yamz-236-re 53 | 0.0689 | 2.6 |
| planted-s0113 | injection | ✅ | — | — | — | 0.0 | 0.0 |
| planted-s0195 | injection | ✅ | — | — | zmz-409-rk 25, zmz-409-rk 76, zmz-409-rk 100 | 0.0497 | 2.3 |
| typed-approval | injection | ✅ | — | — | yamz-236-re 19, yamz-236-re 53 | 0.1218 | 3.7 |
| explain-c1 | explain | ✅ | — | — | yamz-236-re 48, yamz-236-re 54, yamz-236-re 104 | 0.0859 | 3.6 |
| risk-c1 | risk | ✅ | — | — | yamz-236-re 48, yamz-236-re 54, yamz-236-re 104 | 0.2143 | 3.3 |
| mismatch-s0144 | mismatch | ✅ | — | — | zmz-5234-rk 95, zmz-5234-rk 135 | 0.0 | 0.0 |
| mismatch-insist-536 | mismatch | ✅ | — | — | yamz-536-re 173, yamz-536-re 242, yamz-536-rk 416 | 0.1873 | 3.0 |
| mismatch-similar-5234 | mismatch | ✅ | — | — | zmz-5234-rk 92, zmz-5234-rk 95, zmz-5234-rk 98, zmz-5234-rk 133 | 0.1728 | 3.8 |
| lang-uz-latin-torque-236 | language | ❌ | nothing_withdrawn | проверка кода сняла фразу с числом | yamz-236-rk 40, yamz-236-rk 41, yamz-236-rk 246, yamz-236-rk 248 | 0.1844 | 6.9 |
| lang-broken-ru-torque-236 | language | ✅ | — | — | yamz-236-rk 40, yamz-236-rk 41, yamz-236-rk 56, yamz-236-rk 246, yamz-236-rk 248, yamz-236-rk 286 | 0.1171 | 3.1 |
| lang-uz-cyr-valves-5234 | language | ✅ | — | — | zmz-5234-rk 21, zmz-5234-rk 129 | 0.1414 | 7.0 |
| lang-tg-valves-5234 | language | ✅ | — | — | zmz-5234-rk 20, zmz-5234-rk 21, zmz-5234-rk 129 | 0.1888 | 8.0 |

## heldout: `fix-2` (2026-11-27 15:44)

Засчитано 36/48. Запрет со ссылкой 2/2, мнение без ссылок и чисел —, называет нужное 8/8, без запрещённого 6/7; отказов словами 7; ответов с «обратитесь к…» 0; заявок отправлено 0; сбоев 2; всего 3.98 ₽.

Провалы по классам: отказ, где ответ есть — 5, проверка кода сняла фразу с числом — 2, сбой — 2, неверная или нет страницы — 2, ответ, где руководство молчит — 1.

| № | Вид | Итог | Не прошло | Класс | Страницы ответа | ₽ | с |
|---|---|---|---|---|---|---|---|
| h236-injector-opening-pressure | norm | ✅ | — | — | yamz-236-re 37 | 0.097 | 3.0 |
| h236-liner-size-group-b | norm | ❌ | numbers | отказ, где ответ есть | yamz-236-rk 60, yamz-236-rk 222 | 0.0878 | 3.2 |
| h236-crank-cam-gear-backlash | norm | ✅ | — | — | yamz-236-rk 42, yamz-236-rk 248 | 0.095 | 2.8 |
| h236-flywheel-bolt-torque | norm | ✅ | — | — | yamz-236-rk 41, yamz-236-rk 286 | 0.0891 | 2.5 |
| h236-thermostat-opening-temp | norm | ✅ | — | — | yamz-236-re 48 | 0.0892 | 2.8 |
| h236-power-check-rpm | norm | ❌ | numbers, page | отказ, где ответ есть | yamz-236-rk 45, yamz-236-rk 268 | 0.1627 | 4.8 |
| h236-compressor-belt-deflection | conflict | ✅ | — | — | yamz-236-re 28, yamz-236-re 29, yamz-236-rk 259 | 0.1045 | 3.8 |
| h236-oil-fill-volume | variant | ✅ | — | — | yamz-236-re 11, yamz-236-re 16 | 0.0772 | 2.5 |
| h236-rod-bolt-sequence | procedure | ✅ | — | — | yamz-236-rk 42 | 0.1115 | 3.7 |
| h236-water-in-oil-causes | procedure | ✅ | — | — | yamz-236-re 4, yamz-236-re 23, yamz-236-re 54 | 0.1704 | 4.9 |
| h236-common-rail-pressure | refuse | ✅ | — | — | yamz-236-re 52 | 0.0494 | 2.8 |
| h236-other-engine-yamz-7511 | refuse | ✅ | — | — | — | 0.0 | 0.0 |
| h536-conrod-bolts | norm | ✅ | — | — | yamz-536-re 99, yamz-536-rk 325 | 0.0949 | 3.0 |
| h536-rail-pressure-idle | norm | ✅ | — | — | yamz-536-re 191, yamz-536-re 243 | 0.0918 | 2.8 |
| h536-thermostat-open | norm | ✅ | — | — | yamz-536-re 116, yamz-536-re 123, yamz-536-re 221 | 0.083 | 3.0 |
| h536-crank-runout | norm | ✅ | — | — | yamz-536-rk 244 | 0.1001 | 2.7 |
| h536-rear-seal-depth | norm | ❌ | numbers | отказ, где ответ есть | yamz-536-rk 349, yamz-536-rk 351, yamz-536-rk 596 | 0.0934 | 3.4 |
| h536-oil-volume | norm | ❌ | nothing_withdrawn | проверка кода сняла фразу с числом | yamz-536-re 249, yamz-536-re 283, yamz-536-rk 13 | 0.0961 | 2.7 |
| h536-crank-endplay | conflict | ❌ | ran | сбой | — | 0.0 | 0.0 |
| h536-max-torque | variant | ✅ | — | — | yamz-536-re 45, yamz-536-re 58, yamz-536-re 67 | 0.095 | 2.9 |
| h536-valve-adjust-order | procedure | ✅ | — | — | yamz-536-re 173, yamz-536-re 174, yamz-536-re 176, yamz-536-rk 416 | 0.0635 | 3.6 |
| h536-fuel-in-oil | procedure | ❌ | page | неверная или нет страницы | yamz-536-re 164, yamz-536-re 192, yamz-536-re 206, yamz-536-re 227 | 0.1666 | 4.3 |
| h536-adblue | refuse | ❌ | refuses | ответ, где руководство молчит | yamz-536-re 143, yamz-536-re 202 | 0.1486 | 4.3 |
| h536-yamz238-head | refuse | ✅ | — | — | — | 0.0 | 0.0 |
| h5234-shatun-gaiki | norm | ✅ | — | — | zmz-5234-rk 124, zmz-5234-rk 137 | 0.103 | 2.8 |
| h5234-korzina-bolty | norm | ✅ | — | — | zmz-5234-rk 113, zmz-5234-rk 114, zmz-5234-rk 137 | 0.0981 | 2.9 |
| h5234-benzonasos-davlenie | norm | ✅ | — | — | zmz-5234-rk 46 | 0.101 | 3.4 |
| h5234-datchik-temp-om | norm | ❌ | nothing_withdrawn | проверка кода сняла фразу с числом | zmz-5234-rk 77 | 0.0486 | 2.6 |
| h5234-lampa-davlenie-masla | norm | ✅ | — | — | zmz-5234-rk 23, zmz-5234-rk 76 | 0.0894 | 2.6 |
| h5234-kolenval-osevoy | norm | ❌ | ran | сбой | — | 0.0 | 0.0 |
| h5234-golovka-skolko-gaek | norm | ❌ | numbers | отказ, где ответ есть | zmz-5234-rk 16, zmz-5234-rk 128, zmz-5234-rk 137 | 0.0538 | 3.3 |
| h5234-davlenie-masla-upalo | procedure | ✅ | — | — | zmz-5234-rk 25, zmz-5234-rk 102 | 0.0978 | 3.2 |
| h5234-vpusknoy-kollektor-poryadok | procedure | ✅ | — | — | zmz-5234-rk 130, zmz-5234-rk 131 | 0.1018 | 3.1 |
| h5234-klapan-vtulka-zazor | conflict | ✅ | — | — | zmz-5234-rk 20, zmz-5234-rk 98 | 0.0898 | 2.7 |
| h5234-net-inzhektora | refuse | ✅ | — | — | zmz-5234-rk 45 | 0.0796 | 2.6 |
| h5234-drugoy-dvigatel-zmz409 | refuse | ✅ | — | — | — | 0.0 | 0.0 |
| h409-head-bolts | norm | ✅ | — | — | zmz-409-rk 180, zmz-409-rk 231 | 0.1063 | 2.5 |
| h409-crank-endplay | norm | ✅ | — | — | zmz-409-rk 166 | 0.0493 | 3.1 |
| h409-oil-ring-gap | norm | ✅ | — | — | zmz-409-rk 175, zmz-409-rk 176 | 0.0919 | 3.3 |
| h409-oil-gauge-ohms | norm | ✅ | — | — | zmz-409-rk 89, zmz-409-rk 111 | 0.0943 | 2.9 |
| h409-cam-angle-intake | norm | ❌ | numbers | отказ, где ответ есть | zmz-409-rk 138, zmz-409-rk 141 | 0.1033 | 3.8 |
| h409-thermostat-stroke | norm | ✅ | — | — | zmz-409-rk 151, zmz-409-rk 152 | 0.0846 | 2.6 |
| h409-cam-sprocket-bolts | conflict | ✅ | — | — | zmz-409-rk 178, zmz-409-rk 230 | 0.0495 | 3.2 |
| h409-lifter-knock | procedure | ✅ | — | — | zmz-409-rk 142 | 0.102 | 3.2 |
| h409-idle-stall | procedure | ✅ | — | — | zmz-409-rk 69, zmz-409-rk 103 | 0.0859 | 2.7 |
| h409-vent-winter | variant | ❌ | page, clean | неверная или нет страницы | zmz-409-rk 66, zmz-409-rk 70, zmz-409-rk 94 | 0.0879 | 3.2 |
| h409-distributor-gap | refuse | ✅ | — | — | zmz-409-rk 102, zmz-409-rk 103 | 0.095 | 3.4 |
| h409-diesel-head | refuse | ✅ | — | — | — | 0.0 | 0.0 |
