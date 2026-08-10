# События аналитики

События уходят одновременно в **Google Analytics 4** (`gtag('event', …)`) и **Яндекс.Метрику** (`ym(…, 'reachGoal', …)`).

Исходники:

- имена: `frontend/src/lib/analytics/constants.ts`
- отправка: `frontend/src/lib/analytics/trackAnalytics.ts`
- разметка счётчиков: `frontend/src/lib/analytics/injectAnalyticsMarkup.ts`

Переменные окружения (Vite, вшиваются на сборке):

- `VITE_YANDEX_METRIKA_ID`
- `VITE_GA4_MEASUREMENT_ID`

Пример: `frontend/.env.example`. Локально — `frontend/.env.local`.  
Прод (HF Spaces / Docker): ID в `frontend/.env.production` — Vite вшивает их при `npm run build`. Variables в Settings HF на этапе Docker-build обычно **недоступны**, поэтому без `.env.production` счётчики на демо не появятся.

В Яндекс.Метрике для отчётов по целям создайте JavaScript-цели с теми же идентификаторами, что в колонке «Событие» / «Идентификатор» ниже.

Тип цели: **Целевое событие** (ex JS-событие). Условие: **совпадает**.  
Pageview целью не оформляется — это обычные просмотры (первый заход шлёт `ym init` / `gtag config`).

---

## Цели для Яндекс.Метрики (все события)

| Идентификатор | Название цели (пример) | Зачем |
|---------------|------------------------|--------|
| `chat_message_send` | Отправка сообщения | Пользователь задал вопрос |
| `chat_new` | Новый чат | Нажали «Новый чат» |
| `chat_suggestion_click` | Подсказка на старте | Клик по suggestion на welcome |
| `chat_error` | Ошибка ответа | Сбой стрима (RAG или агент) |
| `document_upload` | Загрузка документов | Успешно загрузили файлы |
| `document_upload_error` | Ошибка загрузки | Сбой upload в панели документов |
| `document_delete` | Удаление документа | Удалили файл из панели |
| `document_delete_error` | Ошибка удаления файла | Сбой delete в панели документов |
| `conversation_open_error` | Ошибка открытия чата | Не загрузился диалог из истории |
| `conversation_delete_error` | Ошибка удаления чата | Не удалился диалог |
| `docs_panel_toggle` | Панель документов | Открыли / закрыли «Документы» |
| `category_filter` | Фильтр категории | Сменили категорию поиска |
| `model_change` | Смена модели | Выбрали другую LLM |
| `mode_change` | Режим RAG / Агент | Dropdown «Режим» |
| `agent_run_done` | Ответ агента готов | Финал прогона в режиме AI Агент |
| `theme_toggle` | Смена темы | Светлая / тёмная |
| `language_toggle` | Смена языка | RU ↔ EN |
| `source_click` | Открытие источника | Клик по имени файла → viewer |
| `source_citation_click` | Клик по цитате `[n]` | Маркер в тексте ответа |
| `sources_toggle` | Блок «Источники» | Раскрыли / свернули список |
| `viewer_open` | Просмотрщик открыт | Модалка с файлом |
| `viewer_error` | Ошибка превью | DOCX / XLSX не отрисовался |
| `viewer_download` | Скачать из fallback | Кнопка «Скачать / открыть файл» |
| `viewer_new_tab` | Файл в новой вкладке | Кнопка «В новой вкладке» |
| `viewer_close` | Закрытие просмотрщика | ✕ / Esc / клик по оверлею |

**Приоритет (если не все сразу):** `chat_message_send` → `mode_change` → `agent_run_done` → `document_upload` → `source_click`.

---

## Чат

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `chat_message_send` | Отправка сообщения (composer или Enter) | `model`, `category`, `mode` (`rag` \| `agent`) |
| `chat_new` | Кнопка «Новый чат» | — |
| `chat_suggestion_click` | Клик по подсказке на экране приветствия | `index` (1…3), `mode` |
| `chat_error` | Ошибка стрима ответа (`onError`) | `mode`, `model`, `message` (до 120 символов); для агента ещё `steps` |
| `conversation_open_error` | Не удалось открыть диалог из истории | `conversation_id`, `message` |
| `conversation_delete_error` | Не удалось удалить диалог | `conversation_id`, `message` |

После `chat_suggestion_click` сразу уходит и `chat_message_send` (тот же текст уходит в чат).  
Отмена пользователем (Stop) событием `chat_error` не считается.

---

## Режим RAG / AI Агент

Новый элемент UI — dropdown **«Режим»** (RAG Chat / AI Агент) в top bar и sidebar.

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `mode_change` | Выбрали другой режим в dropdown | `from` (`rag` \| `agent`), `mode` (новое значение) |
| `agent_run_done` | Агент завершил ответ (после ленты шагов) | `steps` (число tool-вызовов), `model` |

В Метрике заведи JS-цели `mode_change`, `agent_run_done`, `chat_error` (условие «совпадает»).  
При ошибке агента уходит `chat_error` (`mode: agent`), без `agent_run_done`.

---

## Документы

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `document_upload` | Успешная загрузка одного или нескольких файлов | `category`, `count` |
| `document_upload_error` | Ошибка при загрузке (catch в панели) | `category`, `count`, `message` (до 120 символов) |
| `document_delete` | Удаление документа из панели | `filename` |
| `document_delete_error` | Ошибка удаления документа | `filename`, `message` |
| `docs_panel_toggle` | Открытие / закрытие панели «Документы» | `open` (`true` \| `false`) |

При ошибке уходит только `*_error`, без парного success-события.

---

## Фильтры поиска

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `category_filter` | Смена категории (top bar / sidebar) | `category` |
| `model_change` | Смена модели (top bar / sidebar) | `model` (id модели, напр. `mock`, `gpt-4o-mini`) |

Автоподстановка модели при открытии старого диалога **не** шлёт `model_change`.

---

## Источники ответа

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `source_click` | Клик по имени файла в карточке источника → просмотрщик | `filename`, `page?` |
| `source_citation_click` | Клик по маркеру `[n]` в тексте ответа | `index`, `filename?`, `page?` |
| `sources_toggle` | Кнопка «Источники · N» | `open` (`true` \| `false`), `count` |

После `source_click` сразу открывается просмотрщик и уходит `viewer_open`.

---

## Просмотрщик документов

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `viewer_open` | Модалка просмотрщика показана | `filename`, `format`, `mode` (`pdf` \| `docx` \| `xlsx` \| `fallback`), `page?` |
| `viewer_error` | Превью DOCX/XLSX упало | те же + `message` |
| `viewer_new_tab` | «В новой вкладке» | те же |
| `viewer_download` | «Скачать / открыть файл» (только fallback, без превью) | те же |
| `viewer_close` | Закрытие (✕ / Esc / оверлей) | те же |

`mode`: `pdf` / `docx` / `xlsx` — встроенный превью; `fallback` — сниппет + кнопка скачать (напр. старый `.doc`).  
Для PDF в iframe отдельного `viewer_error` нет (браузер не отдаёт надёжный onError).

---

## Тема и язык

| Событие | Когда | Параметры |
|---------|--------|-----------|
| `theme_toggle` | Переключение темы в сайдбаре | `theme` (`light` \| `dark`) — новое значение |
| `language_toggle` | Переключение RU / EN | — |

---

## Сводка

| Категория | Кол-во |
|-----------|--------|
| Чат | 6 |
| Документы | 5 |
| Фильтры | 2 |
| Режим RAG / Агент | 2 |
| Источники | 3 |
| Просмотрщик | 5 |
| Тема и язык | 2 |
| **Всего** | **25 именованных** |
