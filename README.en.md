🌍 English | [Русский](README.md)

# 📚 AI RAG Chat — chat with your internal documents

> A **Retrieval-Augmented Generation** assistant over your own documents
> (PDF, Word, Excel). It answers **only from the uploaded files** and shows
> **sources with page-level links**.

### 🔗 Live demo → **https://lyakoway-rag-chat.hf.space**

[![CI](https://github.com/lyakoway/ai-RAG-chat/actions/workflows/ci.yml/badge.svg)](https://github.com/lyakoway/ai-RAG-chat/actions/workflows/ci.yml)
[![Demo](https://img.shields.io/badge/demo-🤗%20Hugging%20Face%20Spaces-ff9d00)](https://lyakoway-rag-chat.hf.space)
![backend](https://img.shields.io/badge/backend-FastAPI-009688)
![frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61dafb)
![vector](https://img.shields.io/badge/vector-ChromaDB-5c2d91)
![license](https://img.shields.io/badge/license-MIT-black)

<sub>On the free tier the demo Space may fall asleep — the first visit after
idle takes ~50 s to wake up.</sub>

## Task and target constraints

Answers over internal documents **with citations pointing to the exact page** —
instead of manually digging through PDF, Word and Excel files. The pipeline was
built against three constraints, each verified by a measurement below:

- **quality** — the right document at the top of retrieval, every fact backed
  by a page-level citation;
- **speed** — first token within seconds (met: ~2.5–3 s on GLM-5.3-flash);
- **accessibility** — the full loop works without API keys (local embeddings +
  offline demo mode).

## Screenshots

| Chat with citations and feedback                        | Vector search with scores                                |
| ------------------------------------------------------- | -------------------------------------------------------- |
| ![Chat with citations](docs/screenshots/chat-citations-ru.png) | ![Vector search](docs/screenshots/vector-search-ru.png) |

Sources with relevance scores and 👍/👎 feedback on answers:

![Sources and feedback](docs/screenshots/sources-feedback-ru.png)

## Features

- 🔀 **Three modes** — **RAG Chat** (one retrieval → answer), **AI Agent** (a tool
  loop with visible steps: list files → search → answer) and **Vector Search**
  (semantic search over chunks without an LLM, with relevance scores). Mode
  switcher in the filter panel.
- 📄 **Search across documents** — PDF, Word (.docx), Excel (.xlsx)
- 📚 **Multiple documents at once** — upload in batches, search across the base
- 🎙️ **Voice input** — ask by voice in chat and in vector search
  (Web Speech API: Chrome, Edge, Safari 14.5+, Android; hidden in Firefox)
- 🔗 **Citations and sources** — every answer references a file and a **page
  number**. The `[1]`, `[2]` markers are **clickable** and highlight the fragment
- 👁️ **Built-in preview** — PDF / DOCX / Excel in a modal. Clicking a source opens
  the fragment (for PDF — right at the cited page)
- 💬 **Conversation history** — all chats are stored, return to any of them
- 🏷️ **Category filtering** — narrow the search to a category (HR, Finance, …)
- 🤖 **Model switcher** — Z.ai (GLM, a **free** tier included), OpenAI (GPT),
  Anthropic (Claude), local (Ollama), or an offline demo mode without keys
- ⚡ **Streaming answers** — tokens arrive in real time (SSE)
- 🎨 **Clean UI** — light/dark theme, responsive layout

## Architecture

```
┌─────────────────┐     /api (SSE + REST)    ┌──────────────────────────┐
│  React + Vite   │ ◀──────────────────────▶ │         FastAPI          │
│ (streaming UI)  │                          │                          │
└─────────────────┘                          │  ┌────────────────────┐  │
                                             │  │ Parsers (pdf/docx/ │  │
                                             │  │        xlsx)       │  │
                                             │  ├────────────────────┤  │
                                             │  │ Chunking (tiktoken)│  │
                                             │  ├────────────────────┤  │
                                             │  │ Embeddings         │  │
                                             │  │ (fastembed/OpenAI) │  │
                                             │  ├────────────────────┤  │
                                             │  │ Vector store       │  │───▶ ChromaDB
                                             │  ├────────────────────┤  │
                                             │  │ RAG pipeline       │  │
                                             │  ├────────────────────┤  │
                                             │  │ LLM providers      │  │───▶ Z.ai (GLM) / OpenAI
                                             │  ├────────────────────┤  │     Anthropic / Ollama
                                             │  │ (mock/gpt/claude/  │  │
                                             │  │  ollama)           │  │
                                             │  └────────────────────┘  │
                                             │   History → SQLite       │
                                             └──────────────────────────┘
```

**Clean backend architecture** (`backend/app/`):

| Layer         | Module                                            | Responsibility                       |
| ------------- | ------------------------------------------------- | ------------------------------------ |
| `api/routes/` | documents, chat, conversations, models, search    | HTTP endpoints, SSE                  |
| `core/`       | ingestion, chunking, embeddings, vectorstore, rag | RAG domain logic                     |
| `parsers/`    | pdf/docx/xlsx                                     | text + page-number extraction        |
| `llm/`        | base, providers, registry                         | LLM provider abstraction             |
| `db/`         | models, session                                   | conversation history (SQLite)        |
| `schemas/`    | dto                                               | API contracts (Pydantic)             |

## Quick start

The app runs **without keys** — in demo mode (mock LLM) with local embeddings.
For real answers add keys to `backend/.env`.

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # optional: add your keys
uvicorn app.main:app --reload --port 8000
```

> The first run downloads a local embedding model (~120 MB) on the first
> document upload.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

### One command (local)

```bash
./dev.sh        # starts backend (:8000) and frontend (:5173)
```

### Via Docker

```bash
docker compose up --build
# frontend: http://localhost:5173   (nginx proxies /api to the backend)
```

Keys can be passed through environment variables:

```bash
OPENAI_API_KEY=sk-... docker compose up --build
```

### Demo documents

Ready-made files live in [`backend/samples/`](backend/samples) (a 3-page PDF,
Word, Excel). The empty Documents panel has a **“Load demo documents”** button —
one click and you can try search and citations right away (clicking again does
not duplicate anything). The batch can also be uploaded via API:
`POST /api/documents/demo`. To regenerate the files:

```bash
cd backend && .venv/bin/python scripts/make_samples.py
```

## Connecting models

| Provider               | How to enable                                                                                                                                                                                       |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Demo (offline)**     | always works, no setup                                                                                                                                                                              |
| **Z.ai (GLM)**         | `ZAI_API_KEY=...` in `backend/.env`. Key: [z.ai/model-api](https://z.ai/model-api). Model list includes the latest `glm-5.3`, `glm-5.3-flash`, `glm-5.2`, plus `glm-4.5-flash` (**free**)             |
| **OpenAI (GPT)**       | `OPENAI_API_KEY=sk-...` in `backend/.env`                                                                                                                                                           |
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY=sk-ant-...` in `backend/.env`                                                                                                                                                    |
| **Ollama (local)**     | install [Ollama](https://ollama.com), `ollama pull llama3.2:3b` (see below)                                                                                                                         |

Unavailable models are marked with a grey dot in the dropdown (no key / model
not pulled / server not running).

> **Z.ai** — an OpenAI-compatible endpoint (`https://api.z.ai/api/paas/v4`),
> reachable without a VPN. The provider supports a custom `base_url`, so any
> OpenAI-compatible gateway can be connected the same way.

### Vector search (fastembed)

The third mode — search over chunks **without an LLM**: the query is encoded by
a local fastembed model (ONNX, multilingual, ~120 MB, no API key), then ChromaDB
returns the nearest chunks by cosine similarity with relevance scores. Clicking
a result opens the document at the right page. The same mechanism powers RAG
Chat and the AI Agent under the hood — this mode is useful to see exactly what
is in the database and with which scores (handy for debugging retrieval
quality). API: `GET /api/search?q=...&category=...&top_k=10`.

### Local models via Ollama

A free option with no keys and no billing — answers are generated on your
machine.

```bash
# 1. Install Ollama: https://ollama.com/download  (or `brew install ollama`)
# 2. Start the server (keep the terminal open):
ollama serve
# 3. In another terminal, pull a model:
ollama pull llama3.2:3b     # 2 GB, fast, good for a demo
#   a smarter option:
ollama pull llama3.1        # 8B, 4.7 GB
```

Check: `curl http://localhost:11434/api/tags` returns the model list. Then
refresh the page — the model becomes active in the “Model” list (no backend
restart needed, availability is checked on every request).

The model registry lives in
[`backend/app/llm/registry.py`](backend/app/llm/registry.py). Pulled a model
with a different tag — add a line there.

#### ⚠️ macOS 13 (Ventura) and older

The official Ollama build targets **macOS 14+** and uses Metal, which crashes
on Ventura with `GGML_ASSERT(buf_dst) failed`. The server itself works — it
just needs to compute on **CPU**. One line in `backend/.env`:

```bash
OLLAMA_NUM_GPU=0      # force CPU (workaround for the macOS 13 Metal bug)
```

> On Ventura run `ollama serve` from a terminal — the Ollama.app GUI does not
> start (requires macOS 14). `brew install ollama` is also discouraged there:
> no ready binary, brew builds from source (slow). Easier to grab a ready
> binary from ollama.com and run the CLI directly.

## Retrieval quality (evaluation)

Retrieval is measured by
[`backend/scripts/evaluate.py`](backend/scripts/evaluate.py): 24 golden
questions (RU + EN) over the bilingual demo documents, Recall@k and MRR metrics
on the same pipeline the chat uses. The index is rebuilt from scratch on every
run — the numbers are reproducible:

```bash
cd backend
.venv/bin/python scripts/evaluate.py             # default config (hybrid)
.venv/bin/python scripts/evaluate.py --rerank    # + cross-encoder rerank
SEARCH_HYBRID=0 .venv/bin/python scripts/evaluate.py   # pure vector search
```

Results on the bilingual corpus (Recall@1 / MRR@5 / latency per query, CPU,
run on Aug 28, 2026):

| Configuration                        | Recall@1  | Recall@3 | MRR@5     | Latency    |
| ------------------------------------ | --------- | -------- | --------- | ---------- |
| Vector search                        | 50.0%     | 95.8%    | 0.733     | 13 ms      |
| **Hybrid BM25 + RRF (default)**      | **91.7%** | 100%     | **0.958** | 15 ms      |
| Vector + reranker                    | 41.7%     | 100%     | 0.694     | ~1.5–3 s   |
| Hybrid + reranker                    | 41.7%     | 100%     | 0.694     | ~1.5–3 s   |

**Interesting finding.** In the bilingual corpus every document has a language
“twin” (RU and EN versions with identical meaning). Vector search confuses
them: the multilingual model's embeddings align the languages, so a Russian
question surfaces the English document (Recall@1 drops to 50%). BM25
distinguishes the vocabulary and pulls up the right document — hybrid reaches
91.7%. The reranker, on the contrary, **hurts** here: the cross-encoder scores
semantic relevance, and the “twin” is just as semantically relevant. Takeaway:
on multilingual corpora the lexical signal in fusion is not optional — it is a
necessity.

Modes are controlled via env: `SEARCH_HYBRID` (default `1`),
`SEARCH_RERANK=1` enables the reranker (an extra ~1 GB model on first run).

### Answer latency (benchmark)

The same approach for the LLM: a live run against the real API (SSE stream of a
RAG answer, the same question, local CPU client). Measured Aug 28, 2026:

| Model                                |           First token (TTFT) | Full answer |
| ------------------------------------ | ---------------------------: | ----------: |
| GLM-5.3-flash (Z.ai)                 |                    2.5–3.0 s |   3.3–3.9 s |
| GLM-5.3 (Z.ai)                       |                        2.6 s |       3.0 s |
| Llama 3.2 3B (Ollama, local, CPU)    | 1.2–3.6 s (cold start +13.7 s) |   2.5–5.4 s |
| GLM-4.5-flash (Z.ai, free)           |                       25–50 s |    39–51 s  |
| Demo mode (mock, no network)         |                        87 ms |       0.5 s |

Additionally:

- agent mode (tool steps + two LLM calls) — 9.2 s on GLM-5.3-flash
- demo pack indexing (6 files → 12 chunks) — 0.7 s
- vector search via API — p50 18 ms server-side

**Takeaway:** latency is defined by the model _generation_, not by settings:
GLM-4.5-flash (the older “thinking” generation, even with `thinking=disabled`)
answers in 25–50 s, while GLM-5.3-flash on the same pipeline — ~3 s. That is
why the free model is not recommended by default.

**Tested hypothesis: trimming the context does not speed up the first token.**
`top_k` 5 → 4 at unchanged Recall (91.7% / 100%) saves ~20% of prefill tokens,
but the gain is not readable on the live API: in alternating runs the
provider's latency spread (2.1–7.2 s) dwarfs the 100–300 ms saving. Chunk size
800 → 400 (Recall also identical) changes nothing at all on the demo corpus:
pages are shorter than 400 tokens, chunks are not re-split. Conclusion: TTFT
~2.5–3 s is the GLM-5.3-flash floor on the provider side. Our pipeline adds
~20 ms (<1%) — there is nothing left to trim; the `top_k=5` and
`chunk 800/120` defaults stay.

**On the local model** (Llama 3.2 3B, Q4_K_M, `OLLAMA_NUM_GPU=0` — CPU on
macOS 13): warm answers are faster than every cloud option (first token
1.2–3.6 s, full answer 2.5–5.4 s), completely free and private. But: the first
request after idle loads 2 GB of model into RAM (+13.7 s), spikes up to 8–15 s
happen under load, and the 3B model drops citations more often and answers
shorter — format accuracy remains with the flagship models.

### Query cost

The context of one RAG answer is ~2–3 thousand tokens (5 chunks of the demo
corpus) plus ~100 tokens of the answer. At Z.ai's list price for GLM-5.3-flash
($0.15 / $0.50 per 1M input/output tokens) that is **≈ $0.0005 per question —
about 20,000 questions per $1**. Zero-cost options: the free `glm-4.5-flash`
and a local Llama via Ollama (computed on your machine). The
quality–speed–cost triangle is thus closed: quality — judge 5.0/5, speed —
TTFT ~2.5–3 s, cost — a fraction of a cent.

## Answer quality (LLM-as-judge)

Retrieval is necessary but not sufficient: does the model answer **correctly**
given the retrieved context? The script has a judge mode: for every golden
question the model generates a real answer (the same RAG pipeline as the
chat), then a second LLM pass — the “judge” — scores the answer on three axes
(1–5): faithfulness to the context, relevance to the question, citation
correctness:

```bash
.venv/bin/python scripts/evaluate.py --judge   # + judge scoring of answers
```

Result on 24 questions (answers and judge: glm-4.5-flash, hybrid retrieval):

| Axis                            | Average score |
| ------------------------------- | ------------- |
| Faithfulness (no hallucinations)| 5.0 / 5       |
| Relevance (answers the question)| 5.0 / 5       |
| Citations (citations correct)   | 5.0 / 5       |

Answers scored ≤3 on at least one axis: 0 of 24 (on the demo corpus).

## Limitations

What I know about the project's boundaries — so the questions don't have to
wait:

- **Corpus.** The evaluation numbers come from a self-made demo corpus
  (6 files, 12 chunks) — this is an upper bound; production needs a golden set
  from real queries (100–300).
- **Judge.** In judge mode the judge is from the same GLM family as the
  answering model — self-judging is lenient. A strict evaluation needs a judge
  from another family: the script already supports `--judge-model`.
- **Security.** The demo runs without authentication and rate limits —
  production needs auth, request limits and token accounting.
- **Load.** No load testing was done — the latency numbers are
  single-user.
- **Prompts.** No automated prompt regression yet: output contracts are fixed,
  model A/B is available in the judge script (`--answer-model` /
  `--judge-model`).

## 🚀 Deploy

The live version is hosted on **Hugging Face Spaces** (Docker) — one container
where **FastAPI serves both the API and the built frontend** from a single
domain (no CORS, no inter-service network). The build is described by the root
[`Dockerfile`](Dockerfile): a multi-stage image — `vite build` first, then the
Python backend serving the static files from `/app/static`.

- Space metadata (SDK, port `7860`) — in the YAML block at the top of
  [README.md](README.md).
- Keys are set as **Space secrets** (`ZAI_API_KEY` etc.) and never enter the
  code.
- For a local two-service setup there is
  [`docker-compose.yml`](docker-compose.yml) (nginx proxies `/api` to the
  backend) — see [Via Docker](#via-docker).

## Tests

The backend is covered with pytest: parsers (PDF/DOCX/XLSX), chunking,
language detection (RU/EN/中文/日本語/한국어), API (demo pack, search, chat with a
mock model, 👍/👎 feedback). Tests run in an isolated `backend/data/test/`
store — working data is untouched:

```bash
cd backend
pip install -r requirements-dev.txt
pytest -q
```

CI (GitHub Actions) runs the backend tests and the frontend build on every
push.

## Stack

- **Backend:** FastAPI, SQLAlchemy (SQLite), ChromaDB, fastembed, pypdf,
  python-docx, openpyxl, tiktoken
- **Frontend:** React 19, TypeScript, Vite, react-markdown
- **LLM:** Z.ai (GLM) / OpenAI / Anthropic / Ollama / mock (custom `base_url`)

## Notes

- The backend defaults to port `8000` (proxied from Vite via `/api`). If the
  port is busy, free it or change `target` in
  [`frontend/vite.config.ts`](frontend/vite.config.ts).
- Data (uploaded files, vector index, history) lives in `backend/data/` and is
  not committed.
- **Settings via link.** Initial language and theme can be set with query
  parameters: `http://localhost:5173/?lang=en&theme=light` (`lang` = `ru`|`en`,
  `theme` = `light`|`dark`). The parameters apply once, get saved and are then
  removed from the URL — the in-app switchers take over. Handy for sharing a
  pre-configured link.
