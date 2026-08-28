"""Retrieval evaluation over the bundled demo documents.

Builds a fresh index from backend/samples in an isolated store
(backend/data/eval), runs a golden question set against the same retrieval
the chat uses, and reports Recall@1/3/5 + MRR as a markdown table.

Запуск:
    cd backend
    .venv/bin/python scripts/evaluate.py            # baseline (векторный поиск)
    .venv/bin/python scripts/evaluate.py --hybrid   # + BM25 (RRF)
    .venv/bin/python scripts/evaluate.py --rerank   # + реранкер fastembed

Индексируется с нуля при каждом запуске — числа воспроизводимы.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
EVAL_DIR = BASE / "data" / "eval"

# Аргументы разбираем ДО импорта app.*: settings создаются при первом импорте,
# и env нужно задать раньше (иначе флаги hybrid/rerank молча не применятся).
_parser = argparse.ArgumentParser()
_parser.add_argument("--hybrid", action="store_true", help="BM25 + векторный поиск (RRF)")
_parser.add_argument("--rerank", action="store_true", help="реранк fastembed после поиска")
_parser.add_argument("--judge", action="store_true", help="LLM-as-judge: получить ответы и оценить их качество")
_parser.add_argument("--answer-model", default="zai:glm-4.5-flash", help="модель для ответов")
_parser.add_argument("--judge-model", default="zai:glm-4.5-flash", help="модель-судья")
_parser.add_argument("--top-k", type=int, default=5)
_parser.add_argument("--limit", type=int, default=0, help="ограничить число вопросов (быстрая проверка)")
_args = _parser.parse_args()

if _args.hybrid:
    os.environ["SEARCH_HYBRID"] = "1"
if _args.rerank:
    os.environ["SEARCH_RERANK"] = "1"
    # Реранкеру нужен пул кандидатов больше итогового top_k.
    os.environ.setdefault("RETRIEVAL_CANDIDATES", "20")

# Изолированное хранилище — env ДО импорта app.* (settings кэшируются).
os.environ["UPLOAD_DIR"] = str(EVAL_DIR / "uploads")
os.environ["CHROMA_DIR"] = str(EVAL_DIR / "chroma")
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DIR / 'app.db'}"
sys.path.insert(0, str(BASE))

from app.config import get_settings  # noqa: E402
from app.core import rag as rag_mod  # noqa: E402
from app.core import vectorstore  # noqa: E402
from app.core.embeddings import active_model_name  # noqa: E402
from app.core.ingestion import ingest_document  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.llm.base import ChatMessage  # noqa: E402
from app.llm.registry import get_provider  # noqa: E402

settings = get_settings()

# Золотой набор: вопрос → документ-источник (по демо-файлам из samples/).
GOLDEN: list[dict] = [
    {"q": "Сколько дней в неделю можно работать удалённо?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "В какие часы сотрудник должен быть на связи онлайн?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "Какая компенсация за интернет положена удалённым сотрудникам?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "До какого числа подаётся заявка на компенсацию интернета?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "Сколько календарных дней длится ежегодный оплачиваемый отпуск?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "За сколько дней до отпуска нужно подать заявление?", "doc": "Политика_удалённой_работы.docx"},
    {"q": "Сколько стоит тариф Старт?", "doc": "Тарифы_и_скидки.xlsx"},
    {"q": "Какой самый дорогой тариф и что в него входит?", "doc": "Тарифы_и_скидки.xlsx"},
    {"q": "Какая скидка даётся при оплате за год?", "doc": "Тарифы_и_скидки.xlsx"},
    {"q": "Есть ли скидка для некоммерческих организаций?", "doc": "Тарифы_и_скидки.xlsx"},
    {"q": "Сколько пользователей включено в тариф Бизнес?", "doc": "Тарифы_и_скидки.xlsx"},
    {"q": "Какие форматы файлов поддерживает импорт данных?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Какой максимальный размер файла для импорта?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Где в интерфейсе запускается импорт данных?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Как включить двухфакторную аутентификацию?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Через сколько минут простоя завершается сессия?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Какие требования к паролю при регистрации?", "doc": "Руководство_пользователя.pdf"},
    {"q": "Кому доступен экспорт данных?", "doc": "Руководство_пользователя.pdf"},
    # --- English (bilingual demo pack) ---
    {"q": "How many days per week can employees work remotely?", "doc": "Remote_Work_Policy.docx", "lang": "en"},
    {"q": "What is the annual paid leave entitlement?", "doc": "Remote_Work_Policy.docx", "lang": "en"},
    {"q": "How much does the Business plan cost per month?", "doc": "Pricing_and_Discounts.xlsx", "lang": "en"},
    {"q": "What discount is offered for annual payment?", "doc": "Pricing_and_Discounts.xlsx", "lang": "en"},
    {"q": "What file formats does data import support?", "doc": "User_Guide.pdf", "lang": "en"},
    {"q": "After how many minutes of inactivity does the session end?", "doc": "User_Guide.pdf", "lang": "en"},
]
# RU-вопросам проставляем язык ответа по умолчанию.
for _item in GOLDEN:
    _item.setdefault("lang", "ru")


JUDGE_SYSTEM_RU = (
    "Ты — строгий оценщик качества RAG-ответов. Даны вопрос, контекст (фрагменты "
    "документов, предоставленные модели) и ответ модели. Оцени ответ по шкале 1-5:\n"
    "- faithfulness: все факты ответа подтверждаются контекстом (5 — полностью, 1 — выдуманы)\n"
    "- relevance: ответ отвечает именно на заданный вопрос\n"
    "- citations: ссылки [n] присутствуют и корректно указывают на источники (нет ссылок — 1)\n"
    'Верни ТОЛЬКО JSON без пояснений: {"faithfulness": N, "relevance": N, '
    '"citations": N, "issues": "кратко о проблемах или пустая строка"}'
)


def _parse_judge_json(text: str) -> dict:
    """Достаёт оценки судьи; при ошибке — нули (будут отброшены агрегатом)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}

    def _clamp(v) -> int:
        try:
            return max(1, min(5, int(v)))
        except (TypeError, ValueError):
            return 0

    return {
        "faithfulness": _clamp(data.get("faithfulness")),
        "relevance": _clamp(data.get("relevance")),
        "citations": _clamp(data.get("citations")),
        "issues": str(data.get("issues", "")).strip(),
    }


async def judge_phase(
    answer_model_id: str, judge_model_id: str, top_k: int, limit: int
) -> None:
    """LLM-as-judge: ответ модели на каждый golden-вопрос + оценка судьёй."""
    import asyncio

    items = GOLDEN[:limit] if limit else GOLDEN
    answer_provider = get_provider(answer_model_id)
    judge_provider = get_provider(judge_model_id)

    rows: list[dict] = []
    for i, item in enumerate(items, 1):
        lang = item.get("lang", "ru")
        hits = vectorstore.query(text=item["q"], top_k=top_k)
        context = rag_mod.build_context(hits)
        system = rag_mod.build_system_prompt(hits, lang)
        print(f"[{i}/{len(items)}] {item['q'][:60]}", flush=True)

        chunks: list[str] = []
        try:
            async for delta in answer_provider.stream(
                system, [ChatMessage(role="user", content=item["q"])], lang
            ):
                chunks.append(delta)
        except Exception as exc:  # noqa: BLE001
            rows.append({**item, "scores": None, "issues": f"ошибка ответа: {exc}"})
            continue
        answer = "".join(chunks).strip()

        judge_user = (
            f"Вопрос: {item['q']}\n\nКонтекст:\n{context[:3000]}\n\nОтвет модели: {answer[:1500]}"
        )
        jchunks: list[str] = []
        try:
            async for delta in judge_provider.stream(
                JUDGE_SYSTEM_RU, [ChatMessage(role="user", content=judge_user)], "ru"
            ):
                jchunks.append(delta)
        except Exception as exc:  # noqa: BLE001
            rows.append({**item, "scores": None, "issues": f"ошибка судьи: {exc}"})
            continue

        scores = _parse_judge_json("".join(jchunks))
        rows.append({**item, "scores": scores, "answer_len": len(answer), "issues": scores.get("issues", "")})
        await asyncio.sleep(0.5)

    scored = [r for r in rows if r["scores"]]
    if not scored:
        print("Судья не вернул ни одной валидной оценки.")
        return

    def _avg(axis: str) -> float:
        vals = [r["scores"][axis] for r in scored if r["scores"].get(axis)]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    print("\n=== LLM-as-judge: агрегаты ===")
    print(f"Оценено ответов: {len(scored)} из {len(rows)}")
    print(f"Faithfulness (верность контексту): {_avg('faithfulness')}/5")
    print(f"Relevance (отвечает на вопрос):   {_avg('relevance')}/5")
    print(f"Citations (корректность цитат):   {_avg('citations')}/5")
    weak = [r for r in scored if min(r["scores"][a] for a in ('faithfulness', 'relevance', 'citations')) <= 3]
    print(f"Ответов с оценкой ≤3 хотя бы по одной оси: {len(weak)}\n")

    print("| # | Вопрос | lang | F | R | C | Проблемы |")
    print("|---|--------|------|---|---|---|----------|")
    for i, r in enumerate(rows, 1):
        s = r["scores"] or {}
        issues = (r.get("issues") or "")[:60]
        print(
            f"| {i} | {r['q'][:52]} | {r.get('lang', 'ru')} "
            f"| {s.get('faithfulness', '—')} | {s.get('relevance', '—')} "
            f"| {s.get('citations', '—')} | {issues} |"
        )


def build_index() -> None:
    """Чистое хранилище + индексация демо-файлов (как POST /api/documents/demo)."""
    shutil.rmtree(EVAL_DIR, ignore_errors=True)
    settings.ensure_dirs()
    init_db()

    db = SessionLocal()
    try:
        for path in sorted(settings.samples_dir.iterdir()):
            ext = path.suffix.lower()
            if ext not in {".pdf", ".docx", ".xlsx"}:
                continue
            import mimetypes
            import shutil as sh

            doc = Document(
                filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                category="Demo",
                status="processing",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            dest = settings.upload_dir / f"{doc.id}{ext}"
            sh.copyfile(path, dest)
            doc.size_bytes = dest.stat().st_size
            db.add(doc)
            db.commit()
            ingest_document(db, doc, dest)
    finally:
        db.close()


def evaluate(top_k: int = 5) -> None:
    rows: list[dict] = []
    latencies: list[float] = []

    for item in GOLDEN:
        started = time.perf_counter()
        hits = vectorstore.query(text=item["q"], top_k=top_k)
        latencies.append((time.perf_counter() - started) * 1000)
        names = [h["filename"] for h in hits]
        rank = next((i + 1 for i, n in enumerate(names) if n == item["doc"]), None)
        rows.append({**item, "rank": rank})

    for k in (1, 3, 5):
        recall = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k) / len(rows)
        print(f"Recall@{k}: {recall:.1%}")
    mrr = sum(1 / r["rank"] for r in rows if r["rank"]) / len(rows)
    print(f"MRR@{top_k}: {mrr:.3f}")
    print(f"Avg retrieval latency: {sum(latencies) / len(latencies):.0f} ms")
    print(f"Model: {active_model_name()}  |  Queries: {len(rows)}\n")

    print("| # | Вопрос | Источник | Rank |")
    print("|---|--------|----------|------|")
    for i, r in enumerate(rows, 1):
        mark = "✅" if r["rank"] else "❌"
        print(f"| {i} | {r['q']} | {r['doc']} | {mark} {r['rank'] or '—'} |")

    misses = [r for r in rows if r["rank"] is None or r["rank"] > 1]
    if misses:
        print("\nНе top-1:")
        for r in misses:
            print(f"  rank {r['rank'] or '—'}: {r['q']}")


if __name__ == "__main__":
    print(
        f"Конфиг: hybrid={_args.hybrid}, rerank={_args.rerank}, "
        f"top_k={_args.top_k}, judge={_args.judge}\n"
    )
    build_index()
    evaluate(_args.top_k)
    if _args.judge:
        import asyncio

        asyncio.run(
            judge_phase(_args.answer_model, _args.judge_model, _args.top_k, _args.limit)
        )
