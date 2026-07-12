# AI RAG Chat — чат с внутренними документами

Портфолио-проект: чат-ассистент с **Retrieval-Augmented Generation** по вашим
документам (PDF, Word, Excel). Отвечает **только по загруженным файлам** и
показывает **источники со ссылками на страницы**.

![stack](https://img.shields.io/badge/backend-FastAPI-009688) ![stack](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61dafb) ![stack](https://img.shields.io/badge/vector-ChromaDB-5c2d91)

<!-- Скриншот: сохраните изображение интерфейса в docs/screenshot.png -->
![Скриншот интерфейса](docs/screenshot.png)

## Возможности

- 📄 **Поиск по документам** — PDF, Word (.docx), Excel (.xlsx)
- 📚 **Несколько документов одновременно** — загружайте пачкой, ищите по всей базе
- 🔗 **Цитаты и источники** — каждый ответ ссылается на файл и **номер страницы**;
  маркеры `[1]`, `[2]` в тексте **кликабельны** и подсвечивают нужный фрагмент
- 👁️ **Встроенный просмотр PDF** — клик по источнику открывает документ прямо
  на **странице цитаты** (для Office-файлов — скачивание/предпросмотр сниппета)
- 💬 **История диалогов** — все чаты сохраняются, к ним можно вернуться
- 🏷️ **Фильтрация по категориям** — ограничьте поиск нужной категорией (HR, Финансы, …)
- 🤖 **Выбор модели** — OpenAI (GPT), Anthropic (Claude), локальная (Ollama) или
  офлайн демо-режим без ключей
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
                                               │  │ LLM providers      │──┼─▶ OpenAI / Anthropic
                                               │  │ (mock/gpt/claude/  │  │   / Ollama
                                               │  │  ollama)           │  │
                                               │  └────────────────────┘  │
                                               │  История → SQLite         │
                                               └──────────────────────────┘
```

**Чистая архитектура бэкенда** (`backend/app/`):

| Слой | Модуль | Ответственность |
|------|--------|-----------------|
| `api/routes/` | documents, chat, conversations, models | HTTP-эндпоинты, SSE |
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

В папке [`samples/`](samples/) лежат готовые файлы (PDF на 3 страницы, Word, Excel)
— загрузите их в панели «Документы», чтобы сразу опробовать поиск и цитаты.
Пересоздать их можно так:

```bash
cd backend && .venv/bin/python scripts/make_samples.py
```

## Подключение моделей

| Провайдер | Как включить |
|-----------|--------------|
| **Demo (offline)** | работает всегда, без настройки |
| **OpenAI (GPT)** | `OPENAI_API_KEY=sk-...` в `backend/.env` |
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY=sk-ant-...` в `backend/.env` |
| **Ollama (локально)** | установите [Ollama](https://ollama.com), `ollama pull llama3.1` |

Недоступные модели помечены в выпадающем списке серой точкой.

## Стек

- **Backend:** FastAPI, SQLAlchemy (SQLite), ChromaDB, fastembed, pypdf,
  python-docx, openpyxl, tiktoken
- **Frontend:** React 19, TypeScript, Vite, react-markdown
- **LLM:** OpenAI / Anthropic / Ollama / mock

## Примечания

- Порт бэкенда по умолчанию — `8000` (проксируется из Vite через `/api`).
  Если порт занят, освободите его или измените `target` в
  [`frontend/vite.config.ts`](frontend/vite.config.ts).
- Данные (загруженные файлы, векторный индекс, история) хранятся в
  `backend/data/` и не коммитятся.
