---
title: AI RAG Chat
emoji: 📚
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# 📚 AI RAG Chat — чат с внутренними документами

> Чат-ассистент с **Retrieval-Augmented Generation** по вашим документам
> (PDF, Word, Excel). Отвечает **только по загруженным файлам** и показывает
> **источники со ссылками на страницы**.

### 🔗 Живое демо → **https://lyakoway-rag-chat.hf.space**

[![Demo](https://img.shields.io/badge/demo-🤗%20Hugging%20Face%20Spaces-ff9d00)](https://lyakoway-rag-chat.hf.space)
![backend](https://img.shields.io/badge/backend-FastAPI-009688)
![frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61dafb)
![vector](https://img.shields.io/badge/vector-ChromaDB-5c2d91)
![license](https://img.shields.io/badge/license-MIT-black)

<sub>Демо на бесплатном тарифе может «засыпать» — первый заход после простоя
поднимается ~50 сек.</sub>

<!-- Скриншот интерфейса: положите файл в docs/screenshot.png и раскомментируйте строку ниже. -->
<!-- ![Скриншот интерфейса](docs/screenshot.png) -->

## Возможности

- 🔀 **Три режима** — **RAG Chat** (один поиск → ответ), **AI Агент** (цикл инструментов
  со видимыми шагами: список файлов → поиск → ответ) и **Векторный поиск** (семантический
  поиск по фрагментам без LLM, с оценкой релевантности). Переключатель в панели фильтров.
- 📄 **Поиск по документам** — PDF, Word (.docx), Excel (.xlsx)
- 📚 **Несколько документов одновременно** — загружайте пачкой, ищите по всей базе
- 🔗 **Цитаты и источники** — каждый ответ ссылается на файл и **номер страницы**;
  маркеры `[1]`, `[2]` в тексте **кликабельны** и подсвечивают нужный фрагмент
- 👁️ **Встроенный просмотр** — PDF / DOCX / Excel в модалке; клик по источнику открывает
  фрагмент (для PDF — сразу на странице цитаты)
- 💬 **История диалогов** — все чаты сохраняются, к ним можно вернуться
- 🏷️ **Фильтрация по категориям** — ограничьте поиск нужной категорией (HR, Финансы, …)
- 🤖 **Выбор модели** — Z.ai (GLM, есть **бесплатная**), OpenAI (GPT),
  Anthropic (Claude), локальная (Ollama) или офлайн демо-режим без ключей
- ⚡ **Стриминг ответов** — токены приходят в реальном времени (SSE)
- 🎨 **Аккуратный UI** — светлая/тёмная тема, адаптивная вёрстка

## Архитектура

```
┌─────────────────┐     /api (SSE + REST)     ┌──────────────────────────┐
│  React + Vite   │ ◀───────────────────────▶ │        FastAPI            │
│  (стриминг UI)  │                            │                          │
└─────────────────┘                            │  ┌────────────────────┐  │
                                               │  │ Parsers (pdf/docx/ │  │
                                               │  │        xlsx)       │  │
                                               │  ├────────────────────┤  │
                                               │  │ Chunking (tiktoken)│  │
                                               │  ├────────────────────┤  │
                                               │  │ Embeddings         │  │
                                               │  │ (fastembed/OpenAI) │  │
                                               │  ├────────────────────┤  │
                                               │  │ Vector store       │──┼─▶ ChromaDB
                                               │  ├────────────────────┤  │
                                               │  │ RAG pipeline       │  │
                                               │  ├────────────────────┤  │
                                               │  │ LLM providers      │──┼─▶ Z.ai (GLM) / OpenAI
                                               │  │ (mock/gpt/claude/  │  │   Anthropic / Ollama
                                               │  │  ollama)           │  │
                                               │  └────────────────────┘  │
                                               │  История → SQLite         │
                                               └──────────────────────────┘
```

**Чистая архитектура бэкенда** (`backend/app/`):

| Слой | Модуль | Ответственность |
|------|--------|-----------------|
| `api/routes/` | documents, chat, conversations, models, search | HTTP-эндпоинты, SSE |
| `core/` | ingestion, chunking, embeddings, vectorstore, rag | доменная логика RAG |
| `parsers/` | pdf/docx/xlsx | извлечение текста + номеров страниц |
| `llm/` | base, providers, registry | абстракция провайдеров LLM |
| `db/` | models, session | история диалогов (SQLite) |
| `schemas/` | dto | контракты API (Pydantic) |

## Быстрый старт

Приложение работает **без ключей** — в демо-режиме (mock LLM) и с локальными
эмбеддингами. Для реальных ответов добавьте ключи в `backend/.env`.

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # опционально: впишите ключи
uvicorn app.main:app --reload --port 8000
```

> Первый запуск скачает локальную модель эмбеддингов (~120 МБ) при первой
> загрузке документа.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Откройте <http://localhost:5173>.

### Одной командой (локально)

```bash
./dev.sh        # поднимает backend (:8000) и frontend (:5173)
```

### Через Docker

```bash
docker compose up --build
# frontend: http://localhost:5173   (nginx проксирует /api на backend)
```

Ключи можно передать через переменные окружения:

```bash
OPENAI_API_KEY=sk-... docker compose up --build
```

### Демо-документы

В папке [`backend/samples/`](backend/samples) лежат готовые файлы (PDF на 3 страницы, Word, Excel).
На пустой панели «Документы» есть кнопка **«Загрузить демо-документы»** — один клик,
и можно сразу пробовать поиск и цитаты (повторное нажатие ничего не дублирует).
Загрузить пачку можно и через API: `POST /api/documents/demo`.
Пересоздать файлы можно так:

```bash
cd backend && .venv/bin/python scripts/make_samples.py
```

## Подключение моделей

| Провайдер | Как включить |
|-----------|--------------|
| **Demo (offline)** | работает всегда, без настройки |
| **Z.ai (GLM)** | `ZAI_API_KEY=...` в `backend/.env`; ключ — на [z.ai/model-api](https://z.ai/model-api). Модель `glm-4.5-flash` **бесплатная** |
| **OpenAI (GPT)** | `OPENAI_API_KEY=sk-...` в `backend/.env` |
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY=sk-ant-...` в `backend/.env` |
| **Ollama (локально)** | установите [Ollama](https://ollama.com), `ollama pull llama3.2:3b` (см. ниже) |

Недоступные модели помечены в выпадающем списке серой точкой (нет ключа / модель
не скачана / сервер не запущен).

> **Z.ai** — OpenAI-совместимый эндпоинт (`https://api.z.ai/api/paas/v4`),
> доступен без VPN. Провайдер поддерживает настраиваемый `base_url`, поэтому
> так же можно подключить любой OpenAI-совместимый шлюз.

### Векторный поиск (fastembed)

Третий режим — поиск по фрагментам **без LLM**: запрос кодируется локальной
моделью fastembed (ONNX, мультиязычная, ~120 МБ, без API-ключа), затем ChromaDB
возвращает ближайшие фрагменты по косинусной близости с оценкой релевантности.
Клик по результату открывает документ на нужной странице. Тот же механизм
работает «под капотом» у RAG Chat и AI Агента — режим полезен, чтобы видеть,
что именно находится в базе и с какими score (удобно для отладки качества
поиска). API: `GET /api/search?q=...&category=...&top_k=10`.

### Локальные модели через Ollama

Бесплатный вариант без ключей и оплаты — ответы генерируются на вашем компьютере.

```bash
# 1. Установите Ollama: https://ollama.com/download  (или `brew install ollama`)
# 2. Запустите сервер (держите терминал открытым):
ollama serve
# 3. В другом терминале скачайте модель:
ollama pull llama3.2:3b     # 2 ГБ, быстрая, хороша для демо
#   при желании умнее:
ollama pull llama3.1        # 8B, 4.7 ГБ
```

Проверка: `curl http://localhost:11434/api/tags` вернёт список моделей.
После этого обновите страницу — модель станет активной в списке «Модель»
(перезапуск бэкенда не требуется, доступность проверяется на каждом запросе).

Реестр моделей — [`backend/app/llm/registry.py`](backend/app/llm/registry.py);
скачали модель с другим тегом — добавьте туда строку.

#### ⚠️ macOS 13 (Ventura) и старше

Официальная сборка Ollama таргетирует **macOS 14+** и использует Metal, который
на Ventura падает с `GGML_ASSERT(buf_dst) failed`. Сам сервер при этом работает —
нужно лишь считать на **CPU**. Включается одной строкой в `backend/.env`:

```bash
OLLAMA_NUM_GPU=0      # форсировать CPU (обход Metal-бага на macOS 13)
```

> На Ventura запускайте `ollama serve` из терминала — GUI-приложение Ollama.app
> не стартует (требует macOS 14). `brew install ollama` там тоже нежелателен:
> нет готового бинарника, brew собирает из исходников (долго). Проще скачать
> готовый бинарник с ollama.com и запускать CLI напрямую.

## Качество поиска (evaluation)

Ретрив измеряется скриптом [`backend/scripts/evaluate.py`](backend/scripts/evaluate.py):
18 золотых вопросов по демо-документам, метрики Recall@k и MRR на том же
пайплайне, что использует чат. Индекс собирается с нуля при каждом запуске —
числа воспроизводимы:

```bash
cd backend
.venv/bin/python scripts/evaluate.py             # векторный поиск (baseline)
.venv/bin/python scripts/evaluate.py --hybrid    # + BM25 через RRF
.venv/bin/python scripts/evaluate.py --rerank    # + cross-encoder реранк
```

Результаты (Recall@1 / MRR@5 / задержка на запрос, CPU):

| Конфигурация | Recall@1 | Recall@3 | MRR@5 | Латентность |
|--------------|----------|----------|-------|-------------|
| Векторный поиск (baseline) | 83.3% | 100% | 0.917 | 13 мс |
| + Гибрид BM25 (RRF) | 88.9% | 100% | 0.944 | 15 мс |
| + Реранкер (bge-reranker-base) | **94.4%** | 100% | **0.972** | ~1.5 с |

Гибрид вытягивает запросы с точными терминами (цифры, названия тарифов), реранкер
поднимает правильный документ на первую позицию. Режимы включаются через env
(`SEARCH_HYBRID=1`, `SEARCH_RERANK=1`) и по умолчанию выключены — демо работает
на одном векторном поиске без скачивания 1-гигабайтного реранкера.

## 🚀 Деплой

Живая версия развёрнута на **Hugging Face Spaces** (Docker) — один контейнер, в
котором **FastAPI отдаёт и API, и собранный фронтенд** с одного домена (без CORS
и межсервисной сети). Сборку описывает корневой [`Dockerfile`](Dockerfile):
многостадийный образ — сначала `vite build`, затем Python-бэкенд, который
раздаёт статику из `/app/static`.

- Метаданные Space (SDK, порт `7860`) — в YAML-блоке в начале этого README.
- Ключи задаются как **секреты Space** (`ZAI_API_KEY` и т.п.), в код не попадают.
- Для локального запуска двумя сервисами есть [`docker-compose.yml`](docker-compose.yml)
  (nginx проксирует `/api` на бэкенд) — см. [Через Docker](#через-docker).

## Стек

- **Backend:** FastAPI, SQLAlchemy (SQLite), ChromaDB, fastembed, pypdf,
  python-docx, openpyxl, tiktoken
- **Frontend:** React 19, TypeScript, Vite, react-markdown
- **LLM:** Z.ai (GLM) / OpenAI / Anthropic / Ollama / mock (настраиваемый `base_url`)

## Примечания

- Порт бэкенда по умолчанию — `8000` (проксируется из Vite через `/api`).
  Если порт занят, освободите его или измените `target` в
  [`frontend/vite.config.ts`](frontend/vite.config.ts).
- Данные (загруженные файлы, векторный индекс, история) хранятся в
  `backend/data/` и не коммитятся.
- **Настройка по ссылке.** Начальные язык и тему можно задать query-параметрами:
  `http://localhost:5173/?lang=en&theme=light` (`lang` = `ru`|`en`, `theme` =
  `light`|`dark`). Параметры применяются один раз, сохраняются и затем убираются
  из адреса — дальше переключатели в интерфейсе главнее. Удобно давать
  преднастроенную ссылку тем, кто открывает проект.
